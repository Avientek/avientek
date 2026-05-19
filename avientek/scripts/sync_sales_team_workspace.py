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
    # Jithin 2026-05-19: also sync shortcuts. Earlier sync only handled
    # number_cards + content, so the on-disk shortcuts list never reached
    # prod — leaving the workspace with too few accessible items for
    # GM-CS users (Frappe v15 sidebar filter hides workspaces whose
    # shortcuts/links all point to things the user can't read).
    ws.set("shortcuts", [])
    for row in spec.get("shortcuts", []):
        ws.append("shortcuts", {
            "label": row.get("label"),
            "link_to": row.get("link_to"),
            "type": row.get("type"),
            "color": row.get("color"),
            "doc_view": row.get("doc_view"),
            "format": row.get("format"),
            "stats_filter": row.get("stats_filter"),
            "url": row.get("url"),
            "kanban_board": row.get("kanban_board"),
            "report_ref_doctype": row.get("report_ref_doctype"),
        })
    ws.content = spec.get("content") or ws.content
    ws.flags.ignore_permissions = True
    ws.flags.ignore_validate = True
    ws.save()
    frappe.db.commit()
    print(f"  ✓ wrote {len(ws.number_cards)} number_cards + {len(ws.shortcuts)} shortcuts on Sales Team")
    for r in ws.number_cards:
        print(f"      [card] {r.number_card_name}")
    for s in ws.shortcuts:
        print(f"      [shortcut] {s.label}  →  {s.type}: {s.link_to}")
