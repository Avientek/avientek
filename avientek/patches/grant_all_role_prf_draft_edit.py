"""Add the "All" role to the Draft state of "Payment Request Form Approval"
workflow.

Client (Jithin, 2026-04-22 spreadsheet row 12) asked that ANY role with
create permission should be allowed to edit a Draft PRF, while submit /
approve transitions stay restricted to the approver roles
(GM / FM / Director / Finance Controller / Accounts Manager).

DocPerms already fit that model: the "All" role has create=1 but
submit=None, and approvers have submit=1 but create=None. The missing
piece was the workflow's allow_edit list — users whose only role was
"All" (no Accounts User / Sales User / etc) landed on the first state
where their role matched, which could be a non-Draft doc_status=1 state.

This patch adds a Draft-state row with allow_edit="All" so the Draft
state is editable by every authenticated user.
"""

import frappe


_WORKFLOW_NAME = "Payment Request Form Approval"
_DRAFT_STATE = "Draft"


def execute():
    if not frappe.db.exists("Workflow", _WORKFLOW_NAME):
        print(f"[grant_all_role_prf_draft_edit] workflow {_WORKFLOW_NAME} missing, skip")
        return

    wf = frappe.get_doc("Workflow", _WORKFLOW_NAME)
    already = any(
        s.state == _DRAFT_STATE and (s.allow_edit or "").strip() == "All"
        for s in wf.states
    )
    if already:
        print("[grant_all_role_prf_draft_edit] All already granted Draft edit, skip")
        return

    wf.append("states", {
        "state": _DRAFT_STATE,
        "doc_status": "0",
        "allow_edit": "All",
    })
    wf.save(ignore_permissions=True)
    frappe.db.commit()
    print("[grant_all_role_prf_draft_edit] added All role to Draft state")
