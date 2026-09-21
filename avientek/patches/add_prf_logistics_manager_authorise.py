"""Add 'Logistics Manager' to the PRF Authorise step.

Background: `create_payment_request_workflow` is registered in patches.txt,
so it runs exactly once per site — edits to that seeder never reach existing
sites. This bridge patch makes the change durable on prod.

Jithin 2026-09-21: add the role "Logistics Manager" to the Payment Request
Form workflow so that a Logistics Manager can Authorise PRFs. Department
scoping (only Logistics-department PRFs) is handled by the visibility layer
— give each Logistics Manager a User Permission of type Department, exactly
like Dept Head (see prf_permissions.py / prf-role-matrix-via-user-permissions
-not-roles). This patch only ensures:
  1. the "Logistics Manager" Role exists (Workflow Transition.allowed is a
     Link to Role, so it must exist first), and
  2. the Draft -> Authorise -> Authorised transition allowed for that role
     exists on the live workflow.

Idempotent — safe to re-run.
"""
import frappe

WORKFLOW = "Payment Request Form Approval"
ROLE = "Logistics Manager"
SOURCE_STATE = "Draft"
ACTION = "Authorise"
NEXT_STATE = "Authorised"


def execute():
	# 1. Role master must exist before a transition can reference it.
	if not frappe.db.exists("Role", ROLE):
		r = frappe.new_doc("Role")
		r.role_name = ROLE
		r.desk_access = 1
		r.insert(ignore_permissions=True)
		print(f"[add_prf_logistics_manager_authorise] Created Role '{ROLE}'")

	if not frappe.db.exists("Workflow", WORKFLOW):
		print(f"[add_prf_logistics_manager_authorise] {WORKFLOW} not present — skipping transition")
		return

	wf = frappe.get_doc("Workflow", WORKFLOW)
	present = any(
		t.state == SOURCE_STATE and t.action == ACTION and t.allowed == ROLE
		for t in (wf.transitions or [])
	)
	if present:
		print("[add_prf_logistics_manager_authorise] transition already present — no change")
		return

	# allow_self_approval=1 mirrors the sibling Authorise rows; the
	# _block_prf_workflow_self_approval after_migrate guard normalises every
	# transition to 0, so self-approval stays disabled site-wide either way.
	wf.append("transitions", {
		"state": SOURCE_STATE,
		"action": ACTION,
		"next_state": NEXT_STATE,
		"allowed": ROLE,
		"allow_self_approval": 1,
	})
	wf.save(ignore_permissions=True)
	frappe.db.commit()
	print(f"[add_prf_logistics_manager_authorise] Added {SOURCE_STATE} -> {ACTION} -> {NEXT_STATE} for '{ROLE}'")
