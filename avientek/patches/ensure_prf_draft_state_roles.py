"""Make sure every role that can CREATE a Payment Request Form can also
edit it in the "Draft" state of the active workflow ("Payment Request Form
Approval").

Without this, Frappe's workflow engine looks for the first state the user's
role can edit — so a user with only General Manager / Director / Finance
Controller / Finance Manager / Accounts Manager would have been dropped
into the first *editable* state matching their role (e.g. "Approved Level 2"
which is doc_status=1), and Save appeared to instantly submit the doc.

Idempotent — skips roles already listed on a Draft state row.
"""

import frappe


_WORKFLOW_NAME = "Payment Request Form Approval"
_DRAFT_STATE = "Draft"
_ROLES_FOR_DRAFT = [
    # The roles that were ALREADY allowed (kept as-is)
    "Sales User",
    "Purchase User",
    "Stock User",
    # Roles that previously skipped Draft and hit a submitted state
    "Accounts User",
    "Accounts Manager",
    "Finance Manager",
    "General Manager",
    "Director",
    "Finance Controller",
    "System Manager",
]


def execute():
    if not frappe.db.exists("Workflow", _WORKFLOW_NAME):
        print(f"[ensure_prf_draft_state_roles] workflow {_WORKFLOW_NAME} missing, skip")
        return

    wf = frappe.get_doc("Workflow", _WORKFLOW_NAME)

    # Collect roles already wired to any Draft state entry so we don't dup
    existing = {
        s.allow_edit for s in wf.states
        if s.state == _DRAFT_STATE and s.allow_edit
    }
    added = 0
    for role in _ROLES_FOR_DRAFT:
        if role in existing:
            continue
        wf.append("states", {
            "state": _DRAFT_STATE,
            "doc_status": "0",
            "allow_edit": role,
        })
        added += 1

    if added:
        wf.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"[ensure_prf_draft_state_roles] added {added} Draft-state role(s)")
    else:
        print("[ensure_prf_draft_state_roles] all roles already allow Draft edit")
