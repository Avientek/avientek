"""Sridhar 2026-07-08 (urgent): procurement.india1 can see supplier Address/
Contact and must be RESTRICTED — the opposite of how ab24462 was read.

Question: can we block procurement.india1 while KEEPING the true procurement/
accounts users (operations2, accounts.india, Harsha — Rahul 2026-07-01) able
to see suppliers? The candidate distinguisher is: does the user hold a Sales
Person User Permission? Classify everyone who currently sees suppliers.

Run: bench --site avintek.local execute avientek.scripts.diag_supplier_gate_review.run
"""
import frappe
from avientek.api.contact_address_access import _user_sees_suppliers, _SUPPLIER_FACING_ROLES
from avientek.api.quotation_access import _get_user_sales_persons

WATCH = [  # users explicitly discussed in the thread
    "procurement.india1@avientek.com", "dispatch.india1@avientek.com",
    "operations2@avientek.com", "accounts.india@avientek.com",
]


def _sees_now(user):
    """Current (ab24462) rule."""
    return _user_sees_suppliers(user)


def _sees_reverted(user):
    """Pure Sales-Person-UP rule (pre-ab24462): sees suppliers only if NO Sales Person UP."""
    return not _get_user_sales_persons(user)


def run():
    # everyone who currently (ab24462) can see suppliers = no SP-UP OR proc/acct role
    proc_role_users = set()
    for role in _SUPPLIER_FACING_ROLES:
        for u in frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"):
            proc_role_users.add(u)
    proc_role_users -= {"Administrator", "Guest"}

    print("=== users with a procurement/accounts role, split by Sales Person UP ===")
    print("(these are the ones whose supplier access DIFFERS between the two rules)\n")
    flips = []
    for u in sorted(proc_role_users):
        if not frappe.db.exists("User", u) or not frappe.db.get_value("User", u, "enabled"):
            continue
        sp = _get_user_sales_persons(u)
        now = _sees_now(u); rev = _sees_reverted(u)
        if now != rev:  # would change under revert
            flips.append(u)
            roles = sorted(set(frappe.get_roles(u)) & _SUPPLIER_FACING_ROLES)
            print(f"  {u:38} SP-UP={'Y' if sp else 'N'}  now={'SEE' if now else 'hide'} -> reverted={'SEE' if rev else 'HIDE'}  {roles}")
    print(f"\n{len(flips)} users would be NEWLY BLOCKED by reverting to the pure Sales-Person-UP rule.")

    print("\n=== watch-list users (explicitly discussed) ===")
    for u in WATCH:
        if not frappe.db.exists("User", u):
            print(f"  {u:38} (not on this bench)"); continue
        sp = _get_user_sales_persons(u)
        print(f"  {u:38} SP-UP={'Y('+str(len(sp))+')' if sp else 'N'}  "
              f"roles={sorted(set(frappe.get_roles(u)) & _SUPPLIER_FACING_ROLES)}  "
              f"now={'SEE' if _sees_now(u) else 'hide'}  reverted={'SEE' if _sees_reverted(u) else 'HIDE'}")
