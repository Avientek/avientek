"""Add the `On Hold` workflow state + 4 transitions to the active
Payment Request Form workflow.

Sridhar/Jithin 2026-06-15 — PRF Enhancement doc §1 ("Hold status on
the Payment Request Form"): Finance Controllers need a way to pause
final processing of a PRF after it has cleared both L1 and L2
approval. The pause must NOT be confused with Reject or Cancel — it
is a temporary suspension.

DESIGN (Q1 decision: Resume returns to Approved Level 2)
  - State: `On Hold`
      style: Warning (orange) — visually distinct from Released
      (Success) and Rejected (Danger).
      doc_status: 1 (submitted) — Hold only applies post-submit.
      allow_edit role: Finance Controller (matches doc spec).
  - Transitions FROM Approved Level 2:
      action `Hold` → next_state `On Hold`, allowed Finance Controller.
  - Transitions FROM On Hold:
      action `Resume` → next_state `Approved Level 2`, FC. (returns
        to the explicit Release step so FC must consciously click
        Release Payment again — single source of truth for
        "ready to release").
      action `Cancel` → `Cancelled`, FC.
      action `Reject` → `Rejected`, FC.

Status Visibility per the doc is naturally satisfied — Frappe
renders workflow_state as a coloured badge in the form's header.
The Warning style on the new state makes "On Hold" jump out next
to Released (green) and Approved Level 2 (green).

Number Card seed (PRF On Hold) is created here too so the Tasks
dashboard gains the same visibility as the existing PRF cards.

Idempotent — every insert is gated on `frappe.db.exists`.
"""

import json
import frappe


_ACTIVE_WORKFLOW = "Payment Request Form Approval"
_HOLD_STATE = "On Hold"
_HOLD_STYLE = "Warning"
_HOLD_DOC_STATUS = 1
_HOLD_EDIT_ROLE = "Finance Controller"

_TRANSITIONS = [
    # (state, action, next_state, allowed_role)
    # Note: this PRF workflow has the unusual design where Rejected.
    # doc_status = 0 (draft). Frappe forbids any transition from
    # doc_status=1 (submitted, like On Hold) → doc_status=0 (draft).
    # The enhancement doc's Hold spec only requires
    # pause / resume / terminal-cancel — not Reject. We give FC the
    # Cancel terminal action which routes to Cancelled (doc_status=2)
    # and leave Reject out. If FC wants to revert the doc to a
    # reviewable state, they Resume → Approved L2 first.
    ("Approved Level 2", "Hold", _HOLD_STATE, "Finance Controller"),
    (_HOLD_STATE, "Resume", "Approved Level 2", "Finance Controller"),
    (_HOLD_STATE, "Cancel", "Cancelled", "Finance Controller"),
]


def execute():
    if not frappe.db.exists("Workflow", _ACTIVE_WORKFLOW):
        # No active PRF workflow on this site — nothing to extend.
        return

    _ensure_global_workflow_state()
    _ensure_workflow_action_masters()
    _ensure_workflow_document_state()
    _ensure_transitions()
    _ensure_number_card()
    _ensure_number_card_on_tasks_workspace()

    frappe.clear_cache(doctype="Payment Request Form")
    # bench execute's NameError fallback path doesn't always commit
    # on a clean return — explicit commit makes the writes survive
    # whether the patch ran via `bench migrate` (which does commit)
    # or via direct `bench execute`.
    frappe.db.commit()


def _ensure_global_workflow_state():
    """The global Workflow State catalog ('tabWorkflow State') is
    shared across all Workflows. Frappe requires a state to exist
    here before it can be referenced from a Workflow Document State.
    """
    if frappe.db.exists("Workflow State", _HOLD_STATE):
        return
    doc = frappe.get_doc({
        "doctype": "Workflow State",
        "workflow_state_name": _HOLD_STATE,
        "style": _HOLD_STYLE,
    })
    doc.insert(ignore_permissions=True)
    print(f"  + Workflow State {_HOLD_STATE!r} created (style={_HOLD_STYLE})")


def _ensure_workflow_action_masters():
    """Frappe validates `Workflow Transition.action` against the
    `Workflow Action Master` doctype (Link field). New action names
    must be registered there first or Workflow.save() throws
    LinkValidationError. The existing PRF workflow uses Authorise /
    Approve Level 1 / Approve Level 2 / Reject / Cancel / Release
    Payment / Revise — all already present. 'Hold' and 'Resume' are
    NEW action names and need master rows.
    """
    for action_name in ("Hold", "Resume"):
        if frappe.db.exists("Workflow Action Master", action_name):
            continue
        am = frappe.get_doc({
            "doctype": "Workflow Action Master",
            "workflow_action_name": action_name,
        })
        am.insert(ignore_permissions=True)
        print(f"  + Workflow Action Master {action_name!r} created")


def _ensure_workflow_document_state():
    """Add `On Hold` as an allowed state within the PRF workflow."""
    wf = frappe.get_doc("Workflow", _ACTIVE_WORKFLOW)
    existing_states = {row.state for row in (wf.states or [])}
    if _HOLD_STATE in existing_states:
        return
    wf.append("states", {
        "state": _HOLD_STATE,
        "doc_status": _HOLD_DOC_STATUS,
        "allow_edit": _HOLD_EDIT_ROLE,
        "update_field": None,
        "update_value": None,
    })
    wf.save(ignore_permissions=True)
    print(f"  + Workflow {_ACTIVE_WORKFLOW!r} gained Document State {_HOLD_STATE!r}")


def _ensure_transitions():
    wf = frappe.get_doc("Workflow", _ACTIVE_WORKFLOW)
    existing = {
        (row.state, row.action, row.next_state, row.allowed)
        for row in (wf.transitions or [])
    }
    added = 0
    for state, action, next_state, allowed in _TRANSITIONS:
        key = (state, action, next_state, allowed)
        if key in existing:
            continue
        wf.append("transitions", {
            "state": state,
            "action": action,
            "next_state": next_state,
            "allowed": allowed,
            "allow_self_approval": 0,
        })
        added += 1
    if added:
        wf.save(ignore_permissions=True)
        print(f"  + {added} workflow transitions inserted")


def _ensure_number_card_on_tasks_workspace():
    """Register the 'PRF On Hold' card on the Tasks workspace so it
    actually shows up alongside the existing 5 PRF cards.

    Sridhar 2026-06-16 (TSK-00342 subtask 1.4): the original patch
    (commit f77a716) created the Number Card but DIDN'T add it to the
    Tasks workspace's content / Workspace Number Card child table.
    Result: card invisible on the dashboard.

    Two writes needed (modern Frappe workspaces use both):
      1. tabWorkspace Number Card (legacy explicit child table)
      2. tabWorkspace.content (v15 JSON layout grid)

    Idempotent — every insert / append gated on existence check.
    """
    WORKSPACE = "Tasks"
    CARD_LABEL = "PRF On Hold"
    CARD_NAME = "PRF On Hold"

    if not frappe.db.exists("Workspace", WORKSPACE):
        return

    ws = frappe.get_doc("Workspace", WORKSPACE)

    # (1) Workspace Number Card child table — add the row if missing
    has_child = any(
        (row.number_card_name or "") == CARD_NAME
        for row in (ws.get("number_cards") or [])
    )
    if not has_child:
        ws.append("number_cards", {
            "label": CARD_LABEL,
            "number_card_name": CARD_NAME,
        })
        print(f"  + Workspace Number Card row appended on {WORKSPACE!r}")

    # (2) Workspace.content JSON — append a `number_card` block if
    # missing. Frappe parses this JSON to render the grid layout.
    try:
        content = json.loads(ws.content or "[]")
    except Exception:
        content = []
    has_block = any(
        isinstance(b, dict)
        and b.get("type") == "number_card"
        and (b.get("data") or {}).get("number_card_name") == CARD_NAME
        for b in content
    )
    if not has_block:
        # Random Frappe-style ID (10 chars). Doesn't need to be globally
        # unique — only unique within this content array.
        import secrets
        block_id = secrets.token_urlsafe(8)[:10]
        content.append({
            "id": block_id,
            "type": "number_card",
            "data": {"number_card_name": CARD_NAME, "col": 4},
        })
        ws.content = json.dumps(content)
        print(f"  + Workspace.content JSON gained number_card block")

    if not has_child or not has_block:
        ws.save(ignore_permissions=True)
        frappe.clear_cache(doctype="Workspace")


def _ensure_number_card():
    if frappe.db.exists("Number Card", "PRF On Hold"):
        return
    card = frappe.get_doc({
        "doctype": "Number Card",
        "name": "PRF On Hold",
        "label": "PRF On Hold",
        "document_type": "Payment Request Form",
        "is_public": 1,
        "show_percentage_stats": 1,
        "stats_time_interval": "Daily",
        "function": "Count",
        "filters_json": json.dumps([
            ["Payment Request Form", "workflow_state", "=", _HOLD_STATE, False]
        ]),
        "color": "#F39C12",  # warning orange
    })
    card.insert(ignore_permissions=True)
    print(f"  + Number Card 'PRF On Hold' created")
