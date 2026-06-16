"""Add the 'PRF On Hold' Number Card to the Tasks workspace so it
actually shows up on the dashboard.

Sridhar 2026-06-16 (TSK-2026-00342 subtask 1.4): the original
'add_prf_on_hold_workflow_state' patch (commit f77a716) created the
Number Card but didn't register it on the Tasks workspace. Patch Log
on prod already marks the original patch as DONE, so it won't
re-run — this is a separate, idempotent patch that picks up the
missed step.

Modern Frappe workspaces store the card grid in TWO places:
  1. tabWorkspace Number Card  — legacy explicit child table
  2. tabWorkspace.content (JSON) — v15 grid layout

Both need the card for it to render correctly. This patch
checks both, only inserts what's missing.
"""

import json
import secrets

import frappe


_WORKSPACE = "Tasks"
_CARD_LABEL = "PRF On Hold"
_CARD_NAME = "PRF On Hold"


def execute():
    if not frappe.db.exists("Workspace", _WORKSPACE):
        return
    if not frappe.db.exists("Number Card", _CARD_NAME):
        # Card itself missing — earlier patch hadn't run. Skip;
        # the workflow patch will create it on next bench migrate.
        return

    ws = frappe.get_doc("Workspace", _WORKSPACE)
    changed = False

    # (1) Child table row
    has_child = any(
        (row.number_card_name or "") == _CARD_NAME
        for row in (ws.get("number_cards") or [])
    )
    if not has_child:
        ws.append("number_cards", {
            "label": _CARD_LABEL,
            "number_card_name": _CARD_NAME,
        })
        changed = True
        print(f"  + Workspace Number Card row appended on {_WORKSPACE!r}")

    # (2) Content JSON block
    try:
        content = json.loads(ws.content or "[]")
    except Exception:
        content = []
    has_block = any(
        isinstance(b, dict)
        and b.get("type") == "number_card"
        and (b.get("data") or {}).get("number_card_name") == _CARD_NAME
        for b in content
    )
    if not has_block:
        block_id = secrets.token_urlsafe(8)[:10]
        content.append({
            "id": block_id,
            "type": "number_card",
            "data": {"number_card_name": _CARD_NAME, "col": 4},
        })
        ws.content = json.dumps(content)
        changed = True
        print(f"  + Workspace.content JSON gained 'PRF On Hold' block")

    if changed:
        ws.save(ignore_permissions=True)
        frappe.clear_cache(doctype="Workspace")
        frappe.db.commit()
