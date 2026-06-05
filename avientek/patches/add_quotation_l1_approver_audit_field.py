"""ERP-TKT-6 — add `Quotation.custom_l1_approved_by` Custom Field.

Captures the user who fired the L1 transition (Approve Level 1 OR
Approve Cancellation Level 1) so a downstream validator can block the
SAME user from also approving at L2. Read-only, hidden — populated
exclusively by the server hook `enforce_l1_l2_different_users` in
`avientek.api.quotation_dual_approval_block`.

Idempotent — re-runs no-op if the Custom Field already exists.
"""
import frappe


CF_NAME = "Quotation-custom_l1_approved_by"


def execute():
    if frappe.db.exists("Custom Field", CF_NAME):
        print(f"[add_quotation_l1_approver_audit_field] {CF_NAME} exists — no-op")
        return

    cf = frappe.new_doc("Custom Field")
    cf.dt = "Quotation"
    cf.fieldname = "custom_l1_approved_by"
    cf.label = "L1 Approved By (Audit)"
    cf.fieldtype = "Link"
    cf.options = "User"
    cf.read_only = 1
    cf.hidden = 1
    cf.no_copy = 1
    cf.print_hide = 1
    cf.report_hide = 1
    cf.allow_on_submit = 1
    # Place after workflow_state — irrelevant since hidden, but keeps
    # the Customize Form export tidy.
    cf.insert_after = "workflow_state"
    cf.description = (
        "ERP-TKT-6: records the user who fired the L1 transition "
        "(Approve Level 1 or Approve Cancellation Level 1). The L2 "
        "transition validator blocks the same user from approving "
        "at both levels. Populated server-side; do not edit."
    )
    cf.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"[add_quotation_l1_approver_audit_field] created {CF_NAME}")
