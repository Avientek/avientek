"""Remove the unused `Pending Level 1 Approval` + `Pending Level 2 Approval`
states (and their dangling transitions) from the active Quotation V3
workflow.

Sridhar/Rahul 2026-06-16: the workflow has TWO parallel "Pending L*
Approval" naming variants:

  - `Pending L1 Approval` / `Pending L2 Approval` (doc_status=1) —
    LIVE: all ENTRY transitions land here (Draft → Send for Approval
    → Pending L1 Approval; Pending L1 → Approve Level 1 → Pending L2).

  - `Pending Level 1 Approval` / `Pending Level 2 Approval`
    (doc_status=0) — DEAD: no transitions ENTER these states, only
    leave them (Approve → Approved; Reject → Draft). They're
    orphaned remnants from an older workflow version and can't be
    reached by any user via the live workflow.

A salesperson seeing two near-identical badge names with OPPOSITE
docstatus semantics ("L1" = submitted-locked, "Level 1" = draft-
editable) can't tell what state their quote is in. Cleanup:

  1. Delete the 4 dangling transitions FROM Pending Level 1/2
     Approval.
  2. Delete the 2 dead Workflow Document State rows.

Audit before this patch (verified on local 2026-06-16):
  Pending L1 Approval         docs=19 (12 docstatus=1, 7 docstatus=0)
  Pending L2 Approval         docs=5  (all docstatus=1)
  Pending Level 1 Approval    docs=0
  Pending Level 2 Approval    docs=0

No data migration needed — zero docs in the dead states.

Number Card filters in
`avientek/avientek/number_card/*.json` defensively include BOTH
naming variants (`workflow_state IN ('Pending L1 Approval',
'Pending Level 1 Approval', …)`) — those stay as-is. After this
patch the dead names simply never appear in production data.

Idempotent — skips if the states are already removed.
"""

import frappe


_ACTIVE_WORKFLOW = "Quotation Approval Workflow Avientek (V3)"
_DEAD_STATES = ("Pending Level 1 Approval", "Pending Level 2 Approval")


def execute():
    if not frappe.db.exists("Workflow", _ACTIVE_WORKFLOW):
        return

    # Hard safety check: refuse to run if any doc actually sits in
    # one of these states. (Audit on 2026-06-16 showed zero — but
    # if data drift happens between deploys, we don't want to orphan
    # docs.)
    stuck = frappe.db.count(
        "Quotation",
        filters={"workflow_state": ("in", _DEAD_STATES)},
    )
    if stuck:
        print(
            f"  ! ABORT: {stuck} Quotation(s) found in dead states "
            f"{_DEAD_STATES}. Investigate before cleanup. Skipping."
        )
        return

    wf = frappe.get_doc("Workflow", _ACTIVE_WORKFLOW)

    # ── Transitions ───────────────────────────────────────────
    # Drop any transition whose source OR target state is dead.
    original_t = len(wf.transitions or [])
    wf.set("transitions", [
        t for t in (wf.transitions or [])
        if t.state not in _DEAD_STATES and t.next_state not in _DEAD_STATES
    ])
    removed_t = original_t - len(wf.transitions)

    # ── States ────────────────────────────────────────────────
    original_s = len(wf.states or [])
    wf.set("states", [
        s for s in (wf.states or [])
        if s.state not in _DEAD_STATES
    ])
    removed_s = original_s - len(wf.states)

    if removed_t == 0 and removed_s == 0:
        return  # Already clean

    wf.save(ignore_permissions=True)
    frappe.clear_cache(doctype="Quotation")
    frappe.db.commit()

    print(
        f"  - removed {removed_t} dangling transition(s) "
        f"and {removed_s} dead Document State row(s) from "
        f"{_ACTIVE_WORKFLOW!r}"
    )
