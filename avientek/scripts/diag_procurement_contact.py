"""Verify the supplier-contact visibility fix (Sridhar 2026-07-06):
  - procurement.india1 (Purchase User + Sales Person UPs) now SEES supplier contacts/addresses.
  - a pure-sales user (Sales Person UP, no procurement role) still does NOT.
  - customer-contact scoping unchanged.

Run: bench --site avintek.local execute avientek.scripts.diag_procurement_contact.run
"""
import frappe
from avientek.api.contact_address_access import (
    _has_permission_link_scoped,
    _user_sees_suppliers,
    contact_permission_query,
)

PROC = "procurement.india1@avientek.com"
PURE_SALES = "st@avientek.com"  # Sales Person UP, no Purchase/Accounts role


def _sample(link_doctype, dt="Contact"):
    row = frappe.db.sql(
        """SELECT dl.parent FROM `tabDynamic Link` dl
           WHERE dl.parenttype=%s AND dl.link_doctype=%s LIMIT 1""",
        (dt, link_doctype),
    )
    return row[0][0] if row else None


def _check(user, dt, link_doctype):
    name = _sample(link_doctype, dt)
    if not name:
        return f"[{link_doctype} {dt}] none found"
    doc = frappe.get_doc(dt, name)
    res = _has_permission_link_scoped(doc, "read", user)
    verdict = {None: "ALLOW", False: "HIDE"}.get(res, res)
    return f"[{link_doctype}-linked {dt} {name}] => {verdict}"


def run():
    for user in (PROC, PURE_SALES):
        print(f"\n=== {user}  _user_sees_suppliers={_user_sees_suppliers(user)} ===")
        print("  " + _check(user, "Contact", "Supplier"))
        print("  " + _check(user, "Address", "Supplier"))
        print("  " + _check(user, "Contact", "Customer"))

    # list-query fragment must now include a supplier branch for PROC
    needle = "link_doctype = 'Supplier'"
    frag = contact_permission_query(PROC) or ""
    print(f"\nPROC list-query includes supplier branch: {needle in frag}")
    frag_s = contact_permission_query(PURE_SALES) or ""
    print(f"PURE_SALES list-query includes supplier branch: {needle in frag_s}")
