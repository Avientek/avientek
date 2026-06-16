"""Remove `Approved → Request Cancellation → Cancellation Requested`
transitions from the active Quotation workflow.

Sridhar 2026-06-16 (TSK-2026-00342 subtask 4.1): on a margin-satisfied
(Approved) Quote, ONLY the direct Cancel button should show — the old
2-level Request Cancellation chain duplicates the button and confuses
users.

After today's `add_quotation_direct_cancel_from_approved` patch
(commit 814cd44), an Approved Quote can be cancelled in one click by
Sales Support L2 / GM-CS / GM / System Manager. The Request
Cancellation path is now redundant. Removing the two transitions
that initiate it from Approved.

WHAT STAYS:
  - The intermediate `Cancellation Requested` and
    `Cancellation L2 Pending` states still exist (in-flight
    cancellation requests already at those states continue through
    their original L1/L2 approval chain — no orphaned docs).
  - The downstream transitions (L1 → L2 approve, withdraw via Cancel
    Request, Reject Cancellation) all stay — anyone with an
    in-progress request can finish it.

WHAT GETS REMOVED:
  - `Approved → Request Cancellation → Cancellation Requested`
    (Sales Support L2)
  - `Approved → Request Cancellation → Cancellation Requested`
    (GM-CS)

After this patch: Approved Quote action menu shows only
`Cancel` (direct, one-shot) — no more `Request Cancellation`.

Idempotent — deletes only the targeted transitions, skips if already
absent.
"""

import frappe


_ACTIVE_WORKFLOW = "Quotation Approval Workflow Avientek (V3)"
_FROM_STATE = "Approved"
_REDUNDANT_ACTION = "Request Cancellation"
_REDUNDANT_NEXT_STATE = "Cancellation Requested"


def execute():
    if not frappe.db.exists("Workflow", _ACTIVE_WORKFLOW):
        return

    wf = frappe.get_doc("Workflow", _ACTIVE_WORKFLOW)
    # Find the rows we want to remove. Match on (state, action,
    # next_state) — every allowed-role variant of this transition
    # goes away.
    drop_indices = []
    for i, row in enumerate(wf.transitions or []):
        if (
            row.state == _FROM_STATE
            and row.action == _REDUNDANT_ACTION
            and row.next_state == _REDUNDANT_NEXT_STATE
        ):
            drop_indices.append((i, row.allowed))

    if not drop_indices:
        return

    # Pop in reverse so indices stay valid
    for i, _ in reversed(drop_indices):
        wf.transitions.pop(i)

    wf.save(ignore_permissions=True)
    frappe.clear_cache(doctype="Quotation")
    frappe.db.commit()

    for _, role in drop_indices:
        print(
            f"  - removed transition: {_FROM_STATE} --[{_REDUNDANT_ACTION}]--> "
            f"{_REDUNDANT_NEXT_STATE} (role: {role})"
        )
