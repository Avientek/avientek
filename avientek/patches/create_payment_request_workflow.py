"""Create Payment Request Form workflow per Jithin's spec (Issue 15).

States: Draft → Authorised → Approved Level 1 → Approved Level 2 → Released
Rejection allowed from any approval state.

Roles:
- Prepare: Sales User, Purchase User, Stock User
- Authorisation: Accounts User, Accounts Manager
- Approval-1: Finance Manager
- Approval-2: General Manager, Director
- Payment Release: Finance Controller
"""

import frappe


WORKFLOW_NAME = "Payment Request Form Approval"
DOCTYPE = "Payment Request Form"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		print(f"[{WORKFLOW_NAME}] DocType {DOCTYPE} not found, skipping")
		return

	# Deactivate any existing workflows on this doctype
	for wf in frappe.get_all("Workflow", filters={"document_type": DOCTYPE}, pluck="name"):
		if wf != WORKFLOW_NAME:
			frappe.db.set_value("Workflow", wf, "is_active", 0)

	# Delete old if exists (so we can recreate cleanly)
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		frappe.delete_doc("Workflow", WORKFLOW_NAME, force=True, ignore_permissions=True)

	# Ensure required Workflow States exist
	required_states = [
		{"name": "Draft", "style": "Warning"},
		{"name": "Authorised", "style": "Info"},
		{"name": "Approved Level 1", "style": "Primary"},
		{"name": "Approved Level 2", "style": "Primary"},
		{"name": "Released", "style": "Success"},
		{"name": "Rejected", "style": "Danger"},
	]
	for s in required_states:
		if not frappe.db.exists("Workflow State", s["name"]):
			doc = frappe.new_doc("Workflow State")
			doc.workflow_state_name = s["name"]
			doc.style = s["style"]
			doc.insert(ignore_permissions=True)

	# Ensure required Roles exist (Finance Controller etc.)
	for role in ["Sales User", "Purchase User", "Stock User",
				 "Accounts User", "Accounts Manager",
				 "Finance Manager", "General Manager", "Director",
				 "Finance Controller"]:
		if not frappe.db.exists("Role", role):
			doc = frappe.new_doc("Role")
			doc.role_name = role
			doc.insert(ignore_permissions=True)

	# Ensure required Workflow Action Master records exist via direct SQL
	# (avoids autoname/validation issues with insert during patch context)
	for action in ["Authorise", "Approve Level 1", "Approve Level 2",
				   "Release Payment", "Reject", "Revise"]:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.db.sql(
				"""INSERT INTO `tabWorkflow Action Master`
				(name, workflow_action_name, owner, modified_by, creation, modified, docstatus, idx)
				VALUES (%s, %s, 'Administrator', 'Administrator', NOW(), NOW(), 0, 0)""",
				(action, action),
			)
	frappe.db.commit()

	# Create workflow
	wf = frappe.new_doc("Workflow")
	wf.workflow_name = WORKFLOW_NAME
	wf.document_type = DOCTYPE
	wf.is_active = 1
	wf.send_email_alert = 0
	wf.workflow_state_field = "workflow_state"

	# States
	wf.append("states", {"state": "Draft", "doc_status": "0", "allow_edit": "Sales User"})
	wf.append("states", {"state": "Draft", "doc_status": "0", "allow_edit": "Purchase User"})
	wf.append("states", {"state": "Draft", "doc_status": "0", "allow_edit": "Stock User"})
	wf.append("states", {"state": "Authorised", "doc_status": "0", "allow_edit": "Accounts Manager"})
	wf.append("states", {"state": "Approved Level 1", "doc_status": "0", "allow_edit": "Finance Manager"})
	wf.append("states", {"state": "Approved Level 2", "doc_status": "1", "allow_edit": "General Manager"})
	wf.append("states", {"state": "Approved Level 2", "doc_status": "1", "allow_edit": "Director"})
	wf.append("states", {"state": "Released", "doc_status": "1", "allow_edit": "Finance Controller"})
	wf.append("states", {"state": "Rejected", "doc_status": "0", "allow_edit": "Accounts Manager"})

	# Transitions
	# Authorise
	for role in ["Accounts User", "Accounts Manager"]:
		wf.append("transitions", {
			"state": "Draft", "action": "Authorise", "next_state": "Authorised",
			"allowed": role, "allow_self_approval": 1,
		})
	# Approve Level 1
	wf.append("transitions", {
		"state": "Authorised", "action": "Approve Level 1", "next_state": "Approved Level 1",
		"allowed": "Finance Manager", "allow_self_approval": 1,
	})
	# Approve Level 2
	for role in ["General Manager", "Director"]:
		wf.append("transitions", {
			"state": "Approved Level 1", "action": "Approve Level 2", "next_state": "Approved Level 2",
			"allowed": role, "allow_self_approval": 1,
		})
	# Release
	wf.append("transitions", {
		"state": "Approved Level 2", "action": "Release Payment", "next_state": "Released",
		"allowed": "Finance Controller", "allow_self_approval": 1,
	})
	# Rejection transitions
	for from_state in ["Authorised", "Approved Level 1", "Approved Level 2"]:
		for role in ["Accounts Manager", "Finance Manager", "General Manager", "Director"]:
			wf.append("transitions", {
				"state": from_state, "action": "Reject", "next_state": "Rejected",
				"allowed": role, "allow_self_approval": 1,
			})
	# Revise (back to Draft)
	wf.append("transitions", {
		"state": "Rejected", "action": "Revise", "next_state": "Draft",
		"allowed": "All", "allow_self_approval": 1,
	})

	wf.insert(ignore_permissions=True)
	frappe.db.commit()
	print(f"[{WORKFLOW_NAME}] Workflow created with {len(wf.states)} states and {len(wf.transitions)} transitions")
