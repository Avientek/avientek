"""Force the Sales Team workspace's number_cards table + content to
match the on-disk JSON. Frappe's reload-doc doesn't always propagate
child-table changes for workspaces; this just reads the file and
overwrites the DB record's number_cards + content fields.
"""
import json
import os
import frappe


def run():
    path = os.path.join(
        frappe.get_app_path("avientek"),
        "avientek", "workspace", "sales_team", "sales_team.json",
    )
    spec = json.load(open(path))
    if not frappe.db.exists("Workspace", "Sales Team"):
        print("Sales Team workspace not in DB; skipping")
        return
    ws = frappe.get_doc("Workspace", "Sales Team")
    ws.set("number_cards", [])
    for row in spec.get("number_cards", []):
        ws.append("number_cards", {
            "label": row.get("label"),
            "number_card_name": row.get("number_card_name"),
        })
    ws.content = spec.get("content") or ws.content
    ws.flags.ignore_permissions = True
    ws.flags.ignore_validate = True
    ws.save()
    frappe.db.commit()
    print(f"  ✓ wrote {len(ws.number_cards)} number_cards rows on Sales Team")
    for r in ws.number_cards:
        print(f"      - {r.number_card_name}")
