"""Rahul 2026-07-08: number cards not visible for GM-CS user dr@ on the CRM
workspace. CRM cards are module=CRM (not Avientek), so this may differ from
the Avientek-module-block issue. Diagnose.

Run: bench --site avintek.local execute avientek.scripts.diag_crm_cards.run
"""
import frappe

USER = "dr@avientek.com"


def run():
    if not frappe.db.exists("User", USER):
        print("user missing on bench"); return
    u = frappe.get_doc("User", USER)
    blocked = sorted(b.module for b in (u.block_modules or []))
    print(f"=== {USER} ===")
    print("blocked modules:", blocked)
    print("  CRM blocked:", "CRM" in blocked, "| Avientek blocked:", "Avientek" in blocked)

    # find the CRM workspace(s) and their number cards
    for ws_name in frappe.get_all("Workspace", filters={"name": ["like", "%CRM%"]}, pluck="name"):
        ws = frappe.get_doc("Workspace", ws_name)
        cards = [r.number_card_name for r in (ws.number_cards or [])]
        print(f"\n=== Workspace '{ws_name}' (module={ws.module}, public={ws.public}) — {len(cards)} number cards ===")
        for nc in cards:
            d = frappe.db.get_value("Number Card", nc,
                ["is_public", "module", "document_type", "owner"], as_dict=True) or {}
            print(f"  {nc:42} public={d.get('is_public')} module={d.get('module') or '-':12} dt={d.get('document_type') or '-'}")
        # what does dr@ actually see?
        frappe.set_user(USER)
        try:
            seen = set(frappe.get_list("Number Card", filters={"name": ["in", cards]},
                pluck="name", limit_page_length=0)) if cards else set()
        finally:
            frappe.set_user("Administrator")
        print(f"  -> dr@ can list {len(seen)}/{len(cards)} of these cards")
        for nc in cards:
            if nc not in seen:
                dt = frappe.db.get_value("Number Card", nc, "document_type")
                print(f"     HIDDEN: {nc}  (doctype={dt}, dr@ read on doctype="
                      f"{frappe.set_user(USER) or frappe.has_permission(dt, ptype='read') if dt else '?'})")
                frappe.set_user("Administrator")
