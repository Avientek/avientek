"""Allow margin-satisfied (Approved) Quotations to be cancelled with
a single click — bypass the existing 2-level L1/L2 cancellation
approval chain.

Sridhar 2026-06-15 follow-up: today an Approved Quotation requires:
    Approved
      -> [Sales Support L2 / GM-CS] Request Cancellation
      -> Cancellation Requested
      -> [GM-CS] Approve Cancellation Level 1
      -> Cancellation L2 Pending
      -> [GM] Approve Cancellation Level 2
      -> Cancelled
… 3 different people touching the doc to retire one quote that the
team has already mutually agreed should go away.

The team has decided this is too heavy for margin-satisfied quotes
(those already passed all internal approvals — re-approving the
cancellation adds no value). This patch ADDS a direct shortcut:

    Approved --[Cancel]--> Cancelled

Allowed roles (mirroring who could touch the existing chain — just
collapsing 3 clicks into 1):
  - Sales Support L2
  - GM-CS
  - GM
  - System Manager

The existing 2-level Request-Cancellation chain stays in place. Any
in-flight cancellation requests already at Cancellation Requested /
Cancellation L2 Pending continue through their original path.
Anyone who prefers the paper-trail flow can still use it.

Idempotent — every insert is gated on `frappe.db.exists`. Safe to
re-run via `bench migrate`.
"""

import frappe


_ACTIVE_WORKFLOW = "Quotation Approval Workflow Avientek (V3)"
_FROM_STATE = "Approved"
_ACTION = "Cancel"
_TO_STATE = "Cancelled"
_ALLOWED_ROLES = ("Sales Support L2", "GM-CS", "GM", "System Manager")


def execute():
    if not frappe.db.exists("Workflow", _ACTIVE_WORKFLOW):
        # Workflow not present on this site — nothing to do.
        return

    # Sanity guard — Approved and Cancelled states must exist already.
    for st in (_FROM_STATE, _TO_STATE):
        if not frappe.db.exists("Workflow State", st):
            frappe.throw(
                f"Workflow State {st!r} missing — cannot add direct "
                "cancel transition. Investigate workflow drift."
            )

    # "Cancel" action master must exist (it does — already used by
    # Submitted/Rejected → Cancel). Defensive check anyway.
    if not frappe.db.exists("Workflow Action Master", _ACTION):
        am = frappe.get_doc({
            "doctype": "Workflow Action Master",
            "workflow_action_name": _ACTION,
        })
        am.insert(ignore_permissions=True)
        print(f"  + Workflow Action Master {_ACTION!r} created")

    added = _ensure_transitions()
    if added:
        print(f"  + {added} direct-cancel transitions inserted on "
              f"{_ACTIVE_WORKFLOW!r}")

    frappe.clear_cache(doctype="Quotation")
    frappe.db.commit()


def _ensure_transitions():
    """Add `Approved --[Cancel]--> Cancelled` for each allowed role.

    Workflow.transitions is a child table — Frappe stores ONE row
    per (state, action, next_state, allowed) tuple. We add one row
    per allowed role.
    """
    wf = frappe.get_doc("Workflow", _ACTIVE_WORKFLOW)
    existing = {
        (row.state, row.action, row.next_state, row.allowed)
        for row in (wf.transitions or [])
    }
    added = 0
    for role in _ALLOWED_ROLES:
        key = (_FROM_STATE, _ACTION, _TO_STATE, role)
        if key in existing:
            continue
        wf.append("transitions", {
            "state": _FROM_STATE,
            "action": _ACTION,
            "next_state": _TO_STATE,
            "allowed": role,
            "allow_self_approval": 0,
        })
        added += 1
    if added:
        wf.save(ignore_permissions=True)
    return added
