"""Sridhar 2026-07-06: st@avientek.com (GM-CS) cannot access the Sales Team
workspace though the workspace allows CS/GM-CS. Root cause = Module Profile
blocks the Avientek module (module-blocked workspaces vanish from the sidebar).

`run`  — diagnose current state.
`test` — reproduce the block for st@, prove the workspace hides, run the
         after_migrate self-heal, prove it comes back. Rolls back the repro.

bench --site avintek.local execute avientek.scripts.diag_sales_team_ws.<fn>
"""
import frappe
from avientek.migrate import _unblock_avientek_module

USER = "st@avientek.com"
WS = "Sales Team"


def _ws_visible(user):
    frappe.set_user(user)
    try:
        from frappe.desk.desktop import get_workspace_sidebar_items
        names = [w.get("name") or w.get("title")
                 for w in get_workspace_sidebar_items().get("pages", [])]
        return WS in names
    finally:
        frappe.set_user("Administrator")


def run():
    u = frappe.get_doc("User", USER)
    print("module_profile:", u.module_profile)
    print("roles:", sorted(r.role for r in u.roles))
    print("User.block_modules has Avientek:",
          "Avientek" in [b.module for b in (u.block_modules or [])])
    print(f"'Sales Team' visible to {USER}: {_ws_visible(USER)}")


def test():
    print(f"baseline: Sales Team visible = {_ws_visible(USER)}")

    # --- reproduce prod: block Avientek on the user (raw child insert to
    # bypass the Module-Profile background job that needs Redis) ---
    row = frappe.new_doc("Block Module")
    row.parent = USER
    row.parenttype = "User"
    row.parentfield = "block_modules"
    row.module = "Avientek"
    row.db_insert()
    frappe.db.commit()
    frappe.clear_cache(user=USER)
    blocked_vis = _ws_visible(USER)
    print(f"after blocking Avientek: Sales Team visible = {blocked_vis}  (expect False)")

    # --- run the self-heal that now lives in after_migrate ---
    _unblock_avientek_module()
    healed_vis = _ws_visible(USER)
    still_blocked = "Avientek" in frappe.db.get_all(
        "Block Module", filters={"parent": USER, "parenttype": "User"}, pluck="module")
    print(f"after _unblock_avientek_module: Sales Team visible = {healed_vis}  (expect True)")
    print(f"user still blocks Avientek: {still_blocked}  (expect False)")

    ok = (blocked_vis is False) and (healed_vis is True) and (not still_blocked)
    print(f"\n{'PASS' if ok else 'FAIL'}: block hides it, self-heal restores it")

    frappe.db.rollback()
    frappe.clear_cache(user=USER)
