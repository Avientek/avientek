"""Sridhar 2026-07-08: Number cards not visible for GM-CS user dr@avientek.com
on the Sales Team workspace. Number Cards have their own perms (is_public /
owner / module / read-perm on the counted doctype). Diagnose.

Run: bench --site avintek.local execute avientek.scripts.diag_number_cards.run
"""
import frappe

USER = "dr@avientek.com"
WS = "Sales Team"


def run():
    print(f"=== {USER} ===")
    if not frappe.db.exists("User", USER):
        print("  user does not exist on this bench"); return
    print("  roles:", sorted(frappe.get_roles(USER)))

    cards = frappe.get_all("Workspace Number Card",
        filters={"parent": WS}, fields=["number_card_name", "label"], order_by="idx")
    print(f"\n=== {len(cards)} number cards referenced by '{WS}' ===")
    print(f"{'card':40}{'exists':7}{'public':7}{'module':16}{'doctype':22}{'owner'}")
    for c in cards:
        name = c.number_card_name
        d = frappe.db.get_value("Number Card", name,
            ["is_public", "module", "document_type", "owner", "type", "report_name"], as_dict=True)
        if not d:
            print(f"{name:40}{'NO':7}--- card doc missing ---")
            continue
        print(f"{name:40}{'yes':7}{str(d.is_public):7}{str(d.module or '-'):16}{str(d.document_type or d.report_name or '-'):22}{d.owner}")

    print(f"\n=== baseline: cards visible to {USER} = {_visible_cards(USER)}/13 ===")


def _visible_cards(user):
    """Count Sales Team number cards the user can actually list — the path the
    desk uses (Number Card permission_query = is_public OR owner, + module)."""
    names = frappe.get_all("Workspace Number Card",
        filters={"parent": WS}, pluck="number_card_name")
    frappe.set_user(user)
    try:
        listed = set(frappe.get_list("Number Card",
            filters={"name": ["in", names]}, pluck="name", limit_page_length=0,
            ignore_permissions=False))
        return len(listed & set(names))
    finally:
        frappe.set_user("Administrator")


def test():
    """Reproduce the prod condition — Avientek module blocked for dr@ — and see
    whether the number cards vanish; then run the after_migrate self-heal."""
    from avientek.migrate import _unblock_avientek_module
    print(f"baseline visible: {_visible_cards(USER)}/13")

    row = frappe.new_doc("Block Module")
    row.parent = USER; row.parenttype = "User"; row.parentfield = "block_modules"; row.module = "Avientek"
    row.db_insert(); frappe.db.commit(); frappe.clear_cache(user=USER)
    blocked = _visible_cards(USER)
    print(f"with Avientek module blocked: {blocked}/13")

    _unblock_avientek_module(); frappe.clear_cache(user=USER)
    healed = _visible_cards(USER)
    print(f"after _unblock_avientek_module: {healed}/13")
    print(f"\nmodule-block hides cards: {blocked < 13}  |  self-heal restores: {healed == 13}")
    frappe.db.rollback(); frappe.clear_cache(user=USER)
