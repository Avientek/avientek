"""Ensure the 'Cancelled (Rejected)' state + Rejected -> Cancel transition
exist on the Payment Request Form Approval workflow.

Background: `create_payment_request_workflow` is registered in
patches.txt, which means it runs exactly once per site — when bench
records it in `tabPatch Log`, future migrations skip it. Edits to that
seeder file (such as the 2026-05-23 Reject->Cancel addition) therefore
never propagate to existing sites unless we ship a separate bridge
patch.

Jithin 2026-05-25 (AVLTD-01528): a Rejected PRF showed only 'Revise' in
the Actions menu — no Cancel option — because the Cancelled (Rejected)
state and the Rejected -> Cancel transition were missing from the live
workflow. Live-patched via API; this patch makes the fix durable.

Idempotent — both branches check first and only insert if missing.
"""
import frappe


WORKFLOW = "Payment Request Form Approval"
STATE = "Cancelled (Rejected)"
SOURCE_STATE = "Rejected"
ACTION = "Cancel"


def execute():
	if not frappe.db.exists("Workflow", WORKFLOW):
		print(f"[ensure_prf_rejected_cancel_transition] {WORKFLOW} not present — skipping")
		return

	# 1. Workflow State master must exist before we can reference it.
	if not frappe.db.exists("Workflow State", STATE):
		ws = frappe.new_doc("Workflow State")
		ws.workflow_state_name = STATE
		ws.style = "Danger"
		ws.insert(ignore_permissions=True)
		print(f"[ensure_prf_rejected_cancel_transition] Created Workflow State '{STATE}'")

	# 2. Workflow Action master 'Cancel' — usually already there, guard anyway.
	if not frappe.db.exists("Workflow Action Master", ACTION):
		wa = frappe.new_doc("Workflow Action Master")
		wa.workflow_action_name = ACTION
		wa.insert(ignore_permissions=True)
		print(f"[ensure_prf_rejected_cancel_transition] Created Workflow Action '{ACTION}'")

	# 3. Append the state row + transition row to the workflow doc if missing.
	wf = frappe.get_doc("Workflow", WORKFLOW)

	state_present = any(s.state == STATE for s in (wf.states or []))
	if not state_present:
		wf.append("states", {
			"state": STATE,
			"doc_status": 0,
			"allow_edit": "All",
			"style": "Danger",
		})

	transition_present = any(
		t.state == SOURCE_STATE and t.action == ACTION
		for t in (wf.transitions or [])
	)
	if not transition_present:
		wf.append("transitions", {
			"state": SOURCE_STATE,
			"action": ACTION,
			"next_state": STATE,
			"allowed": "All",
			"allow_self_approval": 1,
		})

	if not state_present or not transition_present:
		wf.save(ignore_permissions=True)
		frappe.db.commit()
		print(
			f"[ensure_prf_rejected_cancel_transition] Patched workflow — "
			f"states+={0 if state_present else 1}, transitions+={0 if transition_present else 1}"
		)
	else:
		print(f"[ensure_prf_rejected_cancel_transition] Already present — no change")
