"""Verify the dynamic supplier-visibility control in Avientek Settings
(Sridhar 2026-07-08). Reload the doctype, then exercise each mode + the
deny/allow overrides against real users.

Run: bench --site avintek.local execute avientek.scripts.diag_supplier_settings.run
"""
import frappe
from avientek.api.contact_address_access import _user_sees_suppliers

PROC = "procurement.india1@avientek.com"   # has Sales Person UP + Purchase User
OPS = "operations2@avientek.com"           # no Sales Person UP, Purchase User (true procurement)
ACCT = "accounts.india@avientek.com"       # no Sales Person UP, Accounts/Purchase (true accounts)


def _set(**kw):
    s = frappe.get_single("Avientek Settings")
    s.set("supplier_visibility_roles", [])
    s.supplier_visibility_deny_users = kw.get("deny", "")
    s.supplier_visibility_allow_users = kw.get("allow", "")
    s.supplier_visibility_mode = kw.get("mode", "Hide from Sales-Person users")
    if kw.get("roles"):
        for r in kw["roles"]:
            s.append("supplier_visibility_roles", {"role": r})
    s.flags.ignore_permissions = True
    s.save()
    frappe.clear_cache(doctype="Avientek Settings")


def _row(tag):
    def v(u): return "SEE " if _user_sees_suppliers(u) else "hide"
    print(f"  {tag:52} procurement.india1={v(PROC)}  operations2={v(OPS)}  accounts.india={v(ACCT)}")


def run():
    frappe.reload_doc("avientek", "doctype", "avientek_settings")
    frappe.clear_cache(doctype="Avientek Settings")
    print("field exists:", frappe.get_meta("Avientek Settings").has_field("supplier_visibility_mode"))
    print("\n(want: procurement.india1=hide, operations2=SEE, accounts.india=SEE for the default)\n")

    _set(mode="Hide from Sales-Person users")
    _row("mode=Hide from Sales-Person users (DEFAULT)")

    _set(mode="Show to procurement/accounts roles")
    _row("mode=Show to procurement/accounts roles")

    _set(mode="Show to procurement/accounts roles", deny=PROC)
    _row("mode=role + Always-Deny procurement.india1")

    _set(mode="Hide from Sales-Person users", allow=PROC)
    _row("mode=Hide + Always-Allow procurement.india1")

    _set(mode="Unrestricted (show to all)")
    _row("mode=Unrestricted")

    # leave the site on the recommended default that solves the urgent case
    _set(mode="Hide from Sales-Person users")
    frappe.db.commit()
    print("\nLeft Avientek Settings on: Hide from Sales-Person users (procurement.india1 blocked).")
