"""ERP-TKT-6 — prevent same user from approving at both L1 and L2 in
the Quotation V3 workflow.

Root cause: `allow_self_approval=0` on the V3 transitions only blocks
the CREATOR from approving their own quote. It does NOT prevent one
user who's in BOTH approver pools (e.g., orders.mea@avientek.com has
GM-CS = L1 + GM = L2) from rubber-stamping both gates back-to-back.

Real incident — QN-LTD-26-02159-1 (Sridhar 2026-04-18 ticket, captured
on prod 2026-06-03 10:35:13 + 10:35:16 by same user, 3 seconds apart):
margin was 1.84% vs std 6% (30% of std — supposed to be L2-mandatory),
flags correctly set custom_auto_approve_ok=0 and custom_level_1_approve_ok=0,
the workflow routed via Pending For Approval → Pending L2 Approval →
Approved. orders.mea fired BOTH approvals in 3 seconds.

Fix: record who fires the L1 approval (transition INTO Pending L2
Approval or Cancellation L2 Pending) in a Custom Field
`custom_l1_approved_by`, then validate that the L2 transition fires
from a DIFFERENT user.

The Custom Field is added by patch (`add_quotation_l1_approver_audit_field`).
This module wires the record + validate hook on Quotation validate.
"""
import frappe
from frappe import _


L2_PENDING_STATES = ("Pending L2 Approval", "Cancellation L2 Pending")
L2_FINAL_STATES = ("Approved", "Cancelled")


def enforce_l1_l2_different_users(doc, method=None):
    """Record the L1 approver on entry to Pending L2 state, and block
    the same user from finalising at L2.

    Hooked on Quotation `validate`. Frappe fires `validate` on every
    save, INCLUDING saves driven by workflow apply_workflow calls.
    At that point:
      - `doc.workflow_state` is the NEW state (about to be persisted)
      - `doc.get_doc_before_save().workflow_state` is the PREVIOUS state
      - `frappe.session.user` is who's making the change
    """
    # Skip System Manager (administrative overrides — same convention as
    # `_user_has_whitelist_role` elsewhere in this module's siblings)
    if frappe.session.user == "Administrator":
        return

    new_state = (doc.get("workflow_state") or "").strip()
    prev_doc = doc.get_doc_before_save()
    prev_state = (prev_doc.get("workflow_state") if prev_doc else "") or ""
    prev_state = prev_state.strip()

    # Step 1 — entering an L2-pending state: stamp the L1 approver.
    # We stamp on EVERY entry (not just first time) so re-approval
    # after L2-Reject → back to Pending For Approval → re-Approve Level 1
    # correctly captures the new L1 approver.
    if new_state in L2_PENDING_STATES and prev_state not in L2_PENDING_STATES:
        doc.custom_l1_approved_by = frappe.session.user
        return

    # Step 2 — finalising at L2: must be a different user than the one
    # who recorded as custom_l1_approved_by.
    if prev_state in L2_PENDING_STATES and new_state in L2_FINAL_STATES:
        l1_user = (doc.get("custom_l1_approved_by") or "").strip()
        if not l1_user:
            # No L1 user recorded — pre-fix legacy quote. Allow but
            # log so we know.
            frappe.log_error(
                f"Quotation {doc.name}: L2 transition without recorded L1 "
                f"approver. Pre-ERP-TKT-6 legacy doc — letting through.",
                "ERP-TKT-6 legacy bypass",
            )
            return
        if frappe.session.user == l1_user:
            frappe.throw(
                _("L1 and L2 approvals must be by different users.<br><br>"
                  "L1 was approved by <b>{0}</b>; you cannot also approve "
                  "at L2. Ask a different user in the L2 approver pool to "
                  "review and approve.").format(l1_user),
                title=_("Dual-Level Self-Approval Blocked"),
            )
