"""Smoke for Section 1 — Contact & Address Visibility Restriction.

Sridhar/Jithin 2026-06-22 BRD. Verifies:
  T1  Administrator → no restriction (empty SQL fragment)
  T2  Unrestricted user (no Sales Person perms) → no restriction
  T3  Sales-restricted user → fragment generated for Contact + Address
  T4  Fragment SQL is syntactically valid + executes
  T5  Single-doc check: Contact linked ONLY to permitted Customer → allowed
  T6  Single-doc check: Contact linked ONLY to non-permitted Customer → denied
  T7  Single-doc check: Contact linked to BOTH → allowed (OR semantics)
  T8  Single-doc check: Contact with NO Customer link → allowed (out of scope)
  T9  Single-doc check: ptype='write' → defers to Frappe (read-only restriction)
  T10 Creator floor: doc.owner == user → allowed even if no Customer access

Run:
  bench --site avientekv21.local execute \\
    avientek.scripts.smoke_contact_address_visibility.execute
"""
import frappe
from avientek.api.contact_address_access import (
	contact_permission_query,
	address_permission_query,
	contact_has_permission,
	address_has_permission,
	_user_has_customer_restriction,
)


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def _assert(name, cond, detail=""):
	print(f"  [{PASS if cond else FAIL}] {name}{(' — ' + detail) if detail else ''}")
	return bool(cond)


def _find_test_user():
	"""Find a user with Sales Person User Permissions (sales-restricted).
	Fallback: any non-Admin user with the Sales User role."""
	rows = frappe.db.sql(
		"""SELECT DISTINCT up.user
		   FROM `tabUser Permission` up
		   WHERE up.allow = 'Sales Person'
		   LIMIT 1""",
		as_dict=True,
	)
	if rows:
		return rows[0]["user"]
	return None


def execute():
	print("=" * 70)
	print("Contact & Address Visibility — smoke")
	print("=" * 70)

	results = []

	# ── T1: Administrator → empty fragment ──
	print("\nTest 1: Administrator — empty fragment")
	results.append(_assert("contact fragment empty", contact_permission_query("Administrator") == ""))
	results.append(_assert("address fragment empty", address_permission_query("Administrator") == ""))

	# ── T2: Unrestricted user → empty fragment ──
	print("\nTest 2: Unrestricted user — empty fragment")
	# Find any user with NO Sales Person / Customer Group / Company perms
	all_users = frappe.get_all(
		"User", filters={"enabled": 1, "name": ["not in", ("Administrator", "Guest")]},
		fields=["name"], limit_page_length=20,
	)
	unrestricted = None
	for u in all_users:
		if not _user_has_customer_restriction(u.name):
			unrestricted = u.name
			break
	if unrestricted:
		results.append(_assert(
			f"unrestricted user '{unrestricted}' gets empty fragment",
			contact_permission_query(unrestricted) == "",
		))
	else:
		print("  [SKIP] no unrestricted user found on this site")

	# ── T3 + T4: Sales-restricted user → fragment generated + SQL valid ──
	print("\nTest 3+4: Sales-restricted user — fragment generated + SQL executes")
	sales_user = _find_test_user()
	if not sales_user:
		print("  [SKIP] no Sales-Person-restricted user on this site — cannot test SQL path")
	else:
		print(f"  using user: {sales_user}")
		c_frag = contact_permission_query(sales_user)
		a_frag = address_permission_query(sales_user)
		results.append(_assert("contact fragment non-empty", bool(c_frag)))
		results.append(_assert("address fragment non-empty", bool(a_frag)))

		# Execute the fragment — proves it's valid SQL
		try:
			n_contacts = frappe.db.sql(
				f"SELECT COUNT(*) FROM `tabContact` WHERE {c_frag}",
				as_list=True,
			)[0][0]
			results.append(_assert(
				f"contact SQL executes (returns {n_contacts} rows for {sales_user})", True,
			))
		except Exception as e:
			results.append(_assert("contact SQL executes", False, f"SQL error: {e}"))

		try:
			n_addresses = frappe.db.sql(
				f"SELECT COUNT(*) FROM `tabAddress` WHERE {a_frag}",
				as_list=True,
			)[0][0]
			results.append(_assert(
				f"address SQL executes (returns {n_addresses} rows for {sales_user})", True,
			))
		except Exception as e:
			results.append(_assert("address SQL executes", False, f"SQL error: {e}"))

	# ── T5-T10: Single-doc has_permission checks via in-memory docs ──
	print("\nTest 5-10: has_permission single-doc checks")
	if not sales_user:
		print("  [SKIP] no restricted user — cannot exercise has_permission")
	else:
		# Find a customer the user CAN see + a customer they CAN'T.
		# Use the same SQL fragment customer_permission_query uses, so
		# what we pick as "permitted" is guaranteed to pass the EXISTS
		# in our Contact/Address fragment. frappe.get_all(user=...) /
		# frappe.has_permission can disagree on owned/shared edge cases,
		# so go straight to the SQL ground truth.
		from avientek.api.quotation_access import customer_permission_query
		cust_frag = customer_permission_query(sales_user)
		if cust_frag:
			permitted_list = frappe.db.sql_list(
				f"SELECT name FROM `tabCustomer` WHERE {cust_frag} LIMIT 200"
			)
		else:
			permitted_list = []
		permitted_names = set(permitted_list)
		all_customers = frappe.get_all("Customer", fields=["name"], limit_page_length=200)
		non_permitted = next(
			(c.name for c in all_customers if c.name not in permitted_names), None
		)
		permitted_name = next(iter(permitted_names), None)
		print(f"  permitted sample: {permitted_name}  / non-permitted sample: {non_permitted}")

		# Build in-memory mock Contact docs
		def _mk(links, owner="someone-else@x.com"):
			"""Build an in-memory dict shaped like a Contact doc."""
			return frappe._dict({
				"doctype": "Contact",
				"owner": owner,
				"links": [frappe._dict(l) for l in links],
			})

		# T5: only permitted customer
		if permitted_name:
			doc = _mk([{"link_doctype": "Customer", "link_name": permitted_name}])
			r = contact_has_permission(doc, ptype="read", user=sales_user)
			results.append(_assert(
				"T5  Contact→permitted Customer only → allowed (None)", r is None,
				f"got={r}",
			))

		# T6: only non-permitted customer
		if non_permitted:
			doc = _mk([{"link_doctype": "Customer", "link_name": non_permitted}])
			r = contact_has_permission(doc, ptype="read", user=sales_user)
			results.append(_assert(
				"T6  Contact→non-permitted Customer only → denied (False)", r is False,
				f"got={r}",
			))

		# T7: both permitted AND non-permitted (OR semantics)
		if permitted_name and non_permitted:
			doc = _mk([
				{"link_doctype": "Customer", "link_name": permitted_name},
				{"link_doctype": "Customer", "link_name": non_permitted},
			])
			r = contact_has_permission(doc, ptype="read", user=sales_user)
			results.append(_assert(
				"T7  Contact→both (OR semantics) → allowed (None)", r is None,
				f"got={r}",
			))

		# T8: Supplier-only contact — scoped by Supplier Group perms now
		# (Sridhar 2026-06-30). A sales user WITHOUT supplier-group perms
		# must NOT see supplier contacts (the reported bug). A user WITH a
		# matching supplier-group perm should still see them.
		from avientek.api.quotation_access import _get_user_supplier_groups
		sg_perms = _get_user_supplier_groups(sales_user)
		if not sg_perms:
			doc = _mk([{"link_doctype": "Supplier", "link_name": "ANY-SUPPLIER"}])
			r = contact_has_permission(doc, ptype="read", user=sales_user)
			results.append(_assert(
				"T8  Contact→Supplier only, user has NO supplier perms → denied (False)",
				r is False, f"got={r}",
			))
		else:
			# Find a supplier inside the user's permitted groups (allowed)
			# and one outside (denied).
			permitted_sup = frappe.db.sql_list(
				"SELECT name FROM `tabSupplier` WHERE supplier_group IN ({}) LIMIT 1".format(
					", ".join(frappe.db.escape(g) for g in sg_perms)
				)
			)
			if permitted_sup:
				doc = _mk([{"link_doctype": "Supplier", "link_name": permitted_sup[0]}])
				r = contact_has_permission(doc, ptype="read", user=sales_user)
				results.append(_assert(
					"T8  Contact→permitted Supplier → allowed (None)", r is None, f"got={r}",
				))
			outside_sup = frappe.db.sql_list(
				"SELECT name FROM `tabSupplier` WHERE supplier_group NOT IN ({}) LIMIT 1".format(
					", ".join(frappe.db.escape(g) for g in sg_perms)
				)
			)
			if outside_sup:
				doc = _mk([{"link_doctype": "Supplier", "link_name": outside_sup[0]}])
				r = contact_has_permission(doc, ptype="read", user=sales_user)
				results.append(_assert(
					"T8b Contact→non-permitted Supplier → denied (False)", r is False, f"got={r}",
				))

		# T8c: orphan contact (no links at all) → out of scope → allowed
		doc = _mk([])
		r = contact_has_permission(doc, ptype="read", user=sales_user)
		results.append(_assert(
			"T8c Contact→no links at all → allowed (out of scope)", r is None, f"got={r}",
		))

		# T9: ptype='write' should defer
		if non_permitted:
			doc = _mk([{"link_doctype": "Customer", "link_name": non_permitted}])
			r = contact_has_permission(doc, ptype="write", user=sales_user)
			results.append(_assert(
				"T9  ptype='write' → deferred (None) even on non-permitted link",
				r is None, f"got={r}",
			))

		# T10: creator floor
		if non_permitted:
			doc = _mk(
				[{"link_doctype": "Customer", "link_name": non_permitted}],
				owner=sales_user,
			)
			r = contact_has_permission(doc, ptype="read", user=sales_user)
			results.append(_assert(
				"T10 Contact owned by user → allowed (creator floor)",
				r is None, f"got={r}",
			))

	# ── Summary ──
	print("\n" + "=" * 70)
	passed = sum(1 for r in results if r)
	total = len(results)
	print(f"SMOKE: {passed}/{total} passed")
	print("=" * 70)
	if passed != total:
		raise AssertionError(f"{total - passed} assertion(s) failed")
