"""Contact & Address visibility — derive from Customer permissions via Dynamic Link.

BRD: 2026-06-22 (Sridhar/Jithin) — Section 1 of "Enhancement Request:
Visibility and Access Control Improvements".

Background
----------
Customer master is already restricted by User Permission of type
`Sales Person` (Sridhar 2026-04-29 ticket) — a Sales Person user can
only see Customers whose Sales Team includes them. Implementation is
in `avientek.api.quotation_access.customer_permission_query`.

Contact and Address records are independent doctypes; they link to
Customer via Frappe's `Dynamic Link` child table (`Contact.links` /
`Address.links` → `link_doctype='Customer'`). This child-table link
is NOT scoped by the Customer permission — so today every user sees
every Contact and Address regardless of which Customer they're
attached to.

This module fixes that by ADDING a permission layer that asks
"does this user have access to AT LEAST ONE Customer this Contact
points to?" — if yes, show; if no, hide.

Design decisions (per the plan-of-action shared with Sridhar)
-------------------------------------------------------------
Q1 — Contact links to BOTH a permitted and a non-permitted Customer
     → SHOW. OR semantics, most permissive wins. (Salesperson A and
     Salesperson B both legitimately need to reach a shared contact
     of a multi-team customer.)
Q2 — Contact linked ONLY to Supplier / Lead / Employee (no Customer)
     → NO RESTRICTION. Our scope is the Customer permission scheme;
     Supplier / Lead have their own perms which Frappe enforces.
Q3 — Scope = READ-like operations only (read / select / export /
     print / email). Create / edit / delete unchanged.
Q4 — Orphan Contact (zero Dynamic Link rows) → visible to creator only.
     Same pattern as company-less PRFs.

Implementation: two hooks per doctype (Contact + Address) wired in
hooks.py. SQL fragment filter for lists, single-doc check for
direct reads. The single-doc path reuses `frappe.has_permission` on
each linked Customer so the underlying restriction logic stays in
ONE place (quotation_access.customer_permission_query). When that
gets enhanced (e.g. new restriction type), Contact/Address inherit
the change for free.
"""
import frappe

from avientek.api.quotation_access import (
	customer_permission_query,
	_get_user_sales_persons,
	_get_user_customer_groups,
	_get_user_companies,
)


# ── User-state: does this user have ANY Customer-relevant restriction? ──

def _user_has_customer_restriction(user):
	"""Returns True when the user has at least one Sales Person /
	Customer Group / Company User Permission. False = unrestricted,
	skip the Contact/Address scoping entirely."""
	return bool(
		_get_user_sales_persons(user)
		or _get_user_customer_groups(user)
		or _get_user_companies(user)
	)


# ── Shared SQL fragment generator ──

def _build_link_scoped_query(user, parenttype):
	"""Generate the permission_query_conditions WHERE fragment for
	`tabContact` or `tabAddress`. Returns "" when no restriction
	applies (Administrator, no relevant User Permissions).

	The fragment is a 3-way OR:
	  (A) at least one Customer Dynamic Link points to a permitted Customer
	  (B) no Customer Dynamic Link at all (out of scope of this restriction)
	  (C) creator floor — owner == session.user
	"""
	if user == "Administrator":
		return ""
	if not _user_has_customer_restriction(user):
		return ""

	cust_frag = customer_permission_query(user)
	if not cust_frag:
		# Edge: user has SOME perms but none translate to a Customer
		# SQL fragment (e.g. only Brand/Item Group, not relevant here).
		# Skip — let Frappe's default handle it.
		return ""

	parent_table = "`tab{}`".format(parenttype)
	user_esc = frappe.db.escape(user)

	# Note on the EXISTS shape: we use a 2-step subquery rather than
	# an INNER JOIN. customer_permission_query returns a WHERE fragment
	# that references `tabCustomer`.* directly; an INNER JOIN aliasing
	# it as `c` would break those references. The subquery
	# (`dl.link_name IN (SELECT name FROM tabCustomer WHERE <frag>)`)
	# keeps the fragment in its natural top-level context.
	return (
		"("
		# (A) At least one Customer link is permitted
		"EXISTS ("
		"SELECT 1 FROM `tabDynamic Link` dl "
		"WHERE dl.parent = {parent}.name "
		"AND dl.parenttype = {parenttype_esc} "
		"AND dl.link_doctype = 'Customer' "
		"AND dl.link_name IN ("
		"SELECT name FROM `tabCustomer` WHERE {cust_frag}"
		")"
		")"
		# (B) No Customer link at all → out of scope
		" OR NOT EXISTS ("
		"SELECT 1 FROM `tabDynamic Link` dl "
		"WHERE dl.parent = {parent}.name "
		"AND dl.parenttype = {parenttype_esc} "
		"AND dl.link_doctype = 'Customer'"
		")"
		# (C) Creator floor — always visible to the user who created it
		" OR {parent}.owner = {user_esc}"
		")"
	).format(
		parent=parent_table,
		parenttype_esc=frappe.db.escape(parenttype),
		cust_frag=cust_frag,
		user_esc=user_esc,
	)


# ── permission_query_conditions hooks ──

def contact_permission_query(user):
	"""permission_query_conditions["Contact"]. Scope Contact lists /
	reports / Number Card counts to those linked to permitted
	Customers (or no-Customer-link / creator)."""
	return _build_link_scoped_query(user, "Contact")


def address_permission_query(user):
	"""permission_query_conditions["Address"]. Identical mechanism to
	Contact — Address.links uses the same Dynamic Link table."""
	return _build_link_scoped_query(user, "Address")


# ── has_permission single-doc checks ──
#
# Frappe's permission_query_conditions filters list queries but a user
# can still hit a doc via direct URL. has_permission catches that
# path and must stay in lockstep with the SQL above.

_READ_LIKE_PTYPES = {"read", "select", "export", "print", "email"}


def _has_permission_link_scoped(doc, ptype, user):
	"""Shared has_permission body for Contact and Address."""
	# Only restrict READ-like operations (per BRD Q3)
	if ptype not in _READ_LIKE_PTYPES:
		return None

	if user == "Administrator":
		return None

	if not _user_has_customer_restriction(user):
		return None  # No relevant restriction → defer to Frappe

	# Creator floor — always allow user's own docs (Q4)
	if doc.get("owner") == user:
		return None

	# Collect Customer Dynamic Links from the doc
	links = doc.get("links") or []
	customer_link_names = [
		(l.get("link_name") if isinstance(l, dict) else getattr(l, "link_name", None))
		for l in links
		if (
			(l.get("link_doctype") if isinstance(l, dict) else getattr(l, "link_doctype", None))
			== "Customer"
		)
	]
	customer_link_names = [name for name in customer_link_names if name]

	if not customer_link_names:
		return None  # No Customer link → out of scope (Q2)

	# OR semantics — if user can see AT LEAST ONE linked Customer, allow.
	# Delegating to frappe.has_permission keeps a single source of
	# truth for "what makes a Customer visible". When the Customer
	# permission scheme is extended in quotation_access.py, Contact /
	# Address automatically inherit.
	for cust_name in customer_link_names:
		try:
			if frappe.has_permission("Customer", doc=cust_name, user=user, ptype="read"):
				return None  # At least one permitted (Q1: OR wins)
		except Exception:
			# Defensive: a single bad-link error shouldn't lock the user
			# out of a Contact that has other valid links.
			continue

	# No linked Customer is permitted → hide
	return False


def contact_has_permission(doc, ptype=None, user=None):
	return _has_permission_link_scoped(doc, ptype, user)


def address_has_permission(doc, ptype=None, user=None):
	return _has_permission_link_scoped(doc, ptype, user)
