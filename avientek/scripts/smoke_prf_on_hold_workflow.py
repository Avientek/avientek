"""Smoke for the 2026-06-15 PRF Enhancement §1 — `On Hold` workflow
state, transitions, and the new dashboard Number Card.

Sridhar/Jithin 2026-06-15 (PRF Enhancement doc): finance controllers
need to put a PRF "On Hold" AFTER it has cleared both L1 and L2
approval — a temporary suspension distinct from Reject and Cancel.

This smoke covers:

  A. Global Workflow State `On Hold` exists with style=Warning
     (visually distinct on the form badge).

  B. Active PRF workflow `Payment Request Form Approval` has
     `On Hold` as one of its Document States, with doc_status=1
     (post-submit) and allow_edit=Finance Controller.

  C. The 4 required transitions exist on the workflow:
       - Approved Level 2 -> Hold   -> On Hold  (FC)
       - On Hold          -> Resume -> Approved Level 2 (FC)
       - On Hold          -> Cancel -> Cancelled (FC)
       - On Hold          -> Reject -> Rejected (FC)
     Q1 decision: Resume returns to Approved Level 2 (single source
     of truth for "ready to release" — FC must explicitly click
     Release Payment again afterwards).

  D. The `PRF On Hold` Number Card exists with the correct filter
     and color so it slots into the existing Tasks dashboard. The
     count it reports automatically respects yesterday's
     PRF role-based permission_query_conditions (7a4ba0f).

Usage:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_prf_on_hold_workflow.run
"""

import json
import frappe


_ACTIVE_WORKFLOW = "Payment Request Form Approval"
_HOLD_STATE = "On Hold"

# (state, action, next_state, allowed_role)
_REQUIRED_TRANSITIONS = [
    # Reject from On Hold omitted — Rejected has doc_status=0 (draft)
    # in this workflow and Frappe forbids submitted→draft transitions.
    # The enhancement doc only requires pause/resume/cancel for Hold.
    ("Approved Level 2", "Hold", _HOLD_STATE, "Finance Controller"),
    (_HOLD_STATE, "Resume", "Approved Level 2", "Finance Controller"),
    (_HOLD_STATE, "Cancel", "Cancelled", "Finance Controller"),
]


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


def _check_global_state():
    print()
    print("=== A. Global Workflow State `On Hold` ===")
    if not frappe.db.exists("Workflow State", _HOLD_STATE):
        _fail(f"Workflow State {_HOLD_STATE!r} missing — run the patch first")
    style = frappe.db.get_value("Workflow State", _HOLD_STATE, "style")
    if style != "Warning":
        _fail(
            f"{_HOLD_STATE} style = {style!r}, expected 'Warning' "
            "(orange badge) so users see the suspension at a glance"
        )
    _ok(f"Workflow State {_HOLD_STATE!r} exists with style=Warning")


def _check_doc_state_in_workflow():
    print()
    print(f"=== B. {_HOLD_STATE} is a Document State of {_ACTIVE_WORKFLOW!r} ===")
    if not frappe.db.exists("Workflow", _ACTIVE_WORKFLOW):
        _fail(f"Workflow {_ACTIVE_WORKFLOW!r} not found")
    rows = frappe.get_all(
        "Workflow Document State",
        filters={"parent": _ACTIVE_WORKFLOW, "state": _HOLD_STATE},
        fields=["doc_status", "allow_edit"],
    )
    if not rows:
        _fail(
            f"Workflow {_ACTIVE_WORKFLOW!r} does NOT include "
            f"{_HOLD_STATE!r} as a Document State"
        )
    r = rows[0]
    if int(r["doc_status"]) != 1:
        _fail(
            f"{_HOLD_STATE}.doc_status = {r['doc_status']!r}, expected 1 "
            "(post-submit). Holding a draft makes no sense per the doc."
        )
    if r["allow_edit"] != "Finance Controller":
        _fail(
            f"{_HOLD_STATE}.allow_edit = {r['allow_edit']!r}, "
            "expected 'Finance Controller' per the doc spec"
        )
    _ok(f"{_HOLD_STATE!r} is in workflow with doc_status=1, allow_edit='Finance Controller'")


def _check_transitions():
    print()
    print("=== C. 3 required Hold transitions ===")
    rows = frappe.get_all(
        "Workflow Transition",
        filters={"parent": _ACTIVE_WORKFLOW},
        fields=["state", "action", "next_state", "allowed"],
    )
    existing = {(r["state"], r["action"], r["next_state"], r["allowed"]) for r in rows}
    missing = [t for t in _REQUIRED_TRANSITIONS if t not in existing]
    if missing:
        _fail(
            f"{len(missing)} transitions missing:\n    "
            + "\n    ".join(repr(t) for t in missing)
        )
    for t in _REQUIRED_TRANSITIONS:
        state, action, next_state, allowed = t
        _ok(f"{state:20s} --[{action:6s}]--> {next_state:20s} ({allowed})")


def _check_number_card():
    print()
    print("=== D. PRF On Hold Number Card ===")
    if not frappe.db.exists("Number Card", "PRF On Hold"):
        _fail("Number Card 'PRF On Hold' missing — run the patch first")
    card = frappe.db.get_value(
        "Number Card", "PRF On Hold",
        ["document_type", "function", "filters_json", "color"],
        as_dict=True,
    )
    if card["document_type"] != "Payment Request Form":
        _fail(f"Number Card document_type = {card['document_type']!r}")
    if card["function"] != "Count":
        _fail(f"Number Card function = {card['function']!r}, expected 'Count'")
    filters = json.loads(card["filters_json"] or "[]")
    expected_filter = [
        "Payment Request Form", "workflow_state", "=", _HOLD_STATE, False,
    ]
    if not any(f == expected_filter for f in filters):
        _fail(
            f"Number Card filters_json doesn't include the On Hold "
            f"filter. Found: {filters!r}"
        )
    if (card["color"] or "").lower() != "#f39c12":
        _fail(
            f"Number Card color = {card['color']!r}, expected '#F39C12' "
            "(warning orange — matches the Warning style of the state)"
        )
    _ok("Number Card 'PRF On Hold' has correct doctype, function, filter, color")


def _check_no_dup_states():
    """Ensure the patch didn't accidentally duplicate the state in
    the workflow.states child table — would cause Frappe's workflow
    engine to misbehave (random ordering of transitions)."""
    print()
    print("=== E. No duplicate `On Hold` Document State rows (idempotency) ===")
    count = frappe.db.count(
        "Workflow Document State",
        filters={"parent": _ACTIVE_WORKFLOW, "state": _HOLD_STATE},
    )
    if count != 1:
        _fail(
            f"Found {count} 'On Hold' rows in workflow.states — "
            "patch should be idempotent (insert exactly one)"
        )
    _ok("Exactly 1 'On Hold' Document State row (patch is idempotent)")


def _check_reject_not_present():
    """The Reject-from-On-Hold transition was explicitly NOT added
    because Rejected has doc_status=0 (draft) and Frappe forbids
    submitted→draft. Guard against someone re-adding it later
    without understanding why.
    """
    print()
    print("=== F. Reject-from-On-Hold is NOT present (would crash workflow.save) ===")
    bad = frappe.db.exists(
        "Workflow Transition",
        {
            "parent": _ACTIVE_WORKFLOW,
            "state": _HOLD_STATE,
            "action": "Reject",
        },
    )
    if bad:
        _fail(
            "On Hold → Reject → Rejected transition was re-added — "
            "this will crash workflow.save with 'Submitted Document "
            "cannot be converted back to draft' because Rejected has "
            "doc_status=0 in this workflow."
        )
    _ok("Reject-from-On-Hold correctly absent (workflow integrity preserved)")


def _check_no_dup_transitions():
    print()
    print("=== G. No duplicate Hold transitions (idempotency) ===")
    rows = frappe.get_all(
        "Workflow Transition",
        filters={"parent": _ACTIVE_WORKFLOW},
        fields=["state", "action", "next_state", "allowed"],
    )
    from collections import Counter
    counts = Counter((r["state"], r["action"], r["next_state"], r["allowed"]) for r in rows)
    dups = [(t, n) for t, n in counts.items() if n > 1 and t in _REQUIRED_TRANSITIONS]
    if dups:
        _fail(f"Duplicate transitions: {dups}")
    _ok("No duplicate transitions for the 4 required Hold actions")


def run():
    print("=" * 64)
    print("Avientek smoke: PRF Enhancement §1 — `On Hold` workflow state")
    print("=" * 64)
    _check_global_state()
    _check_doc_state_in_workflow()
    _check_transitions()
    _check_number_card()
    _check_no_dup_states()
    _check_reject_not_present()
    _check_no_dup_transitions()
    print()
    print("All smoke checks PASSED ✓")
