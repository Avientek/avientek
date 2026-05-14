# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Restore the margin-based approval gate that the V3 Quotation workflow
# seeder dropped from the V2 / "Quotation Final" workflow.
#
# Jithin 2026-05-17 — QN-LTD-26-02011 (party C-AETPL-00392, brand std
# margin 6%) was submitted on 2026-05-13 with -1.52% total margin
# WITHOUT going through L1/L2 approval. Root cause: the V3 workflow's
# `Draft → Submit → Submitted` transition had `condition = ""`,
# allowing anyone to submit any quote regardless of `set_margin_flags`
# output. The legacy V2 workflow (fixtures/workflow.json) gated the
# same transition on `doc.custom_auto_approve_ok == 1`.
#
# This patch:
#   1. Adds the margin condition to the Submit transition so the
#      button auto-hides in the UI for low-margin quotes.
#   2. Adds a new "Send for Approval" transition from Draft →
#      Pending For Approval (allowed for All, condition: margin
#      requires approval). This gives the sales user the correct
#      action to take when the Submit button is hidden.
#
# Server-side enforcement (avientek.events.quotation.
# validate_margin_approval_required) is the source of truth — even
# if a user bypasses the workflow via REST API the validate hook
# throws. The workflow condition is for UX so the bad action just
# doesn't appear.
#
# Idempotent: re-running won't duplicate transitions or re-apply
# already-correct conditions.

import frappe


WORKFLOW_NAME = "Quotation Approval Workflow Avientek (V3)"

AUTO_APPROVE_OK_CONDITION = "doc.custom_auto_approve_ok == 1"
NEEDS_APPROVAL_CONDITION = "doc.custom_auto_approve_ok == 0"

SEND_FOR_APPROVAL_FROM_DRAFT = {
    "state": "Draft",
    "action": "Send for Approval",
    "next_state": "Pending For Approval",
    "allowed": "All",
    "condition": NEEDS_APPROVAL_CONDITION,
}


def execute():
    if not frappe.db.exists("Workflow", WORKFLOW_NAME):
        print(f"restore_quotation_margin_gate_on_v3_workflow: workflow '{WORKFLOW_NAME}' not found — skipping")
        return

    wf = frappe.get_doc("Workflow", WORKFLOW_NAME)
    changed = False

    # 1. Add margin condition to Draft → Submit → Submitted
    for t in wf.transitions:
        if (
            t.state == "Draft"
            and t.action == "Submit"
            and t.next_state == "Submitted"
        ):
            if (t.condition or "") != AUTO_APPROVE_OK_CONDITION:
                t.condition = AUTO_APPROVE_OK_CONDITION
                changed = True

    # 2. Ensure Draft → Send for Approval → Pending For Approval exists
    has_send_for_approval = any(
        (t.state == "Draft" and t.next_state == "Pending For Approval"
         and t.action == "Send for Approval")
        for t in wf.transitions
    )
    if not has_send_for_approval:
        wf.append("transitions", SEND_FOR_APPROVAL_FROM_DRAFT)
        changed = True

    if changed:
        wf.save(ignore_permissions=True)
        frappe.db.commit()
        print(
            f"restore_quotation_margin_gate_on_v3_workflow: updated '{WORKFLOW_NAME}' "
            f"(transitions={len(wf.transitions)})"
        )
    else:
        print("restore_quotation_margin_gate_on_v3_workflow: no change needed (idempotent)")
