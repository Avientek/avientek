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

	# Force delete any existing workflow + orphaned child rows via direct SQL
	# (previous failed patch attempts may have left partial records)
	frappe.db.sql("DELETE FROM `tabWorkflow` WHERE name = %s", WORKFLOW_NAME)
	frappe.db.sql("DELETE FROM `tabWorkflow Document State` WHERE parent = %s", WORKFLOW_NAME)
	frappe.db.sql("DELETE FROM `tabWorkflow Transition` WHERE parent = %s", WORKFLOW_NAME)
	frappe.db.commit()

	# Ensure required Workflow States exist
	required_states = [
		{"name": "Draft", "style": "Warning"},
		{"name": "Authorised", "style": "Info"},
		{"name": "Approved Level 1", "style": "Primary"},
		{"name": "Approved Level 2", "style": "Primary"},
		{"name": "Released", "style": "Success"},
		{"name": "Rejected", "style": "Danger"},
		# Jithin 2026-05-12: new Cancelled state (doc_status=2) so
		# Finance Controller can cancel a Released / Approved L2 doc
		# (Frappe forbids doc_status 1->0).
		{"name": "Cancelled", "style": "Danger"},
		# Jithin 2026-05-23 (AVLTD-01528): user wants the ability to
		# Cancel a Rejected PRF (doc_status=0). Frappe forbids workflow
		# transitions from doc_status=0 to doc_status=2 directly, so we
		# need a separate state at doc_status=0 for this flow. Keeping
		# the word "Cancelled" in the name so filter/search "Cancelled"
		# finds both this and the post-submit Cancelled state.
		{"name": "Cancelled (Rejected)", "style": "Danger"},
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
				 "Finance Controller",
				 # Jithin 2026-05-12: Dept Head joins the Authorisation step.
				 "Dept Head"]:
		if not frappe.db.exists("Role", role):
			doc = frappe.new_doc("Role")
			doc.role_name = role
			doc.insert(ignore_permissions=True)

	# Ensure required Workflow Action Master records exist via direct SQL
	# (avoids autoname/validation issues with insert during patch context)
	for action in ["Authorise", "Approve Level 1", "Approve Level 2",
				   "Release Payment", "Reject", "Revise",
				   # Jithin 2026-05-12: Finance Controller can Cancel.
				   "Cancel"]:
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
	# Jithin 2026-05-13: After Authorise the doc must be FROZEN for the
	# Accounts Manager (the actor who authorised). Only the next-step
	# approver (Finance Manager) plus System Manager may edit fields on
	# the Authorised state — closes the audit gap where the same user
	# could keep saving changes after their own Authorise click.
	wf.append("states", {"state": "Authorised", "doc_status": "0", "allow_edit": "Finance Manager"})
	wf.append("states", {"state": "Authorised", "doc_status": "0", "allow_edit": "System Manager"})
	wf.append("states", {"state": "Approved Level 1", "doc_status": "0", "allow_edit": "Finance Manager"})
	wf.append("states", {"state": "Approved Level 2", "doc_status": "1", "allow_edit": "General Manager"})
	wf.append("states", {"state": "Approved Level 2", "doc_status": "1", "allow_edit": "Director"})
	wf.append("states", {"state": "Released", "doc_status": "1", "allow_edit": "Finance Controller"})
	wf.append("states", {"state": "Rejected", "doc_status": "0", "allow_edit": "Accounts Manager"})
	# Rahul 2026-05-22 (AVLTD-01517): Issued Bank + Payment Mode edit
	# is now role-driven — read the role pool from Avientek Settings
	# (`issued_bank_edit_roles` table) and grant allow_edit to each role
	# on EVERY pre-Released state. Once the PRF transitions to Released,
	# only the existing Finance Controller allow_edit row above applies
	# (per-field lock enforced by JS apply_fc_field_unlock — restricts
	# the editable surface to issued_bank + payment_mode only).
	# Defaults to ["Finance Controller", "System Manager"] when the
	# settings table is empty.
	# Only states this base seeder defines above. Other pre-Released
	# states (Pending For Approval / Sent For Approval / Pending L1 /
	# Pending L2) are added by separate after_migrate patches and
	# inherit their own allow_edit rows when those patches run — see
	# avientek/patches/prf_internal_party_skip_l2.py etc.
	_pre_released_states_for_issued_bank_edit = [
		# state name, doc_status
		("Draft", "0"),
		("Authorised", "0"),
		("Approved Level 1", "0"),
		("Approved Level 2", "1"),
	]
	# Rahul 2026-05-22: read EXACTLY what's in the table — empty list
	# is a deliberate "no extra roles" admin choice. The base seeder
	# already covers Finance Manager (Authorised + Approved L1), GM
	# / Director (Approved L2), and Finance Controller (Released), so
	# emptying the table doesn't lock out the standard workflow.
	try:
		_issued_bank_edit_roles = frappe.get_all(
			"Avientek Quote Role",
			filters={
				"parent": "Avientek Settings",
				"parenttype": "Avientek Settings",
				"parentfield": "issued_bank_edit_roles",
			},
			fields=["role"],
			pluck="role",
		) or []
	except Exception:
		_issued_bank_edit_roles = []
	# Dedup against any allow_edit rows already appended above for the
	# same (state, role) pair so MariaDB doesn't trip on duplicates.
	_already_added = {
		(s.state, s.allow_edit)
		for s in wf.get("states") or []
	}
	for _state, _docstatus in _pre_released_states_for_issued_bank_edit:
		for _role in _issued_bank_edit_roles:
			if not _role or (_state, _role) in _already_added:
				continue
			wf.append("states", {
				"state": _state,
				"doc_status": _docstatus,
				"allow_edit": _role,
			})
			_already_added.add((_state, _role))
	wf.append("states", {"state": "Cancelled", "doc_status": "2", "allow_edit": "Finance Controller"})
	# Jithin 2026-05-23 (AVLTD-01528): doc_status=0 "Cancelled" sibling
	# for the Rejected → Cancel path.
	wf.append("states", {"state": "Cancelled (Rejected)", "doc_status": "0", "allow_edit": "Finance Controller"})

	# Transitions
	# Authorise — Accounts User, Accounts Manager, plus Dept Head (Jithin 2026-05-12)
	for role in ["Accounts User", "Accounts Manager", "Dept Head"]:
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
	# Rejection transitions — only from unsubmitted states (Authorised, Approved Level 1).
	# Approved Level 2 is already submitted (doc_status=1), so cannot be reverted to Rejected (doc_status=0).
	# Jithin 2026-05-12: Accounts Manager should NOT be able to Reject *after* Authorisation —
	# they did the authorise step, the reject decision belongs to the upstream approvers.
	# (Reject from "Approved Level 1" keeps Accounts Manager.)
	for from_state in ["Authorised", "Approved Level 1"]:
		reject_roles = ["Accounts Manager", "Finance Manager", "General Manager", "Director"]
		if from_state == "Authorised":
			reject_roles = [r for r in reject_roles if r != "Accounts Manager"]
		for role in reject_roles:
			wf.append("transitions", {
				"state": from_state, "action": "Reject", "next_state": "Rejected",
				"allowed": role, "allow_self_approval": 1,
			})
	# Revise (back to Draft)
	wf.append("transitions", {
		"state": "Rejected", "action": "Revise", "next_state": "Draft",
		"allowed": "All", "allow_self_approval": 1,
	})

	# Cancel — Finance Controller can cancel from any active state.
	# doc_status 0 -> 0 routes to Rejected. doc_status 1 -> 2 routes to
	# new Cancelled state (Frappe forbids 1 -> 0 transitions, and 0 -> 2
	# is also blocked, so each branch picks the legal target).
	for from_state in ["Authorised", "Approved Level 1"]:  # doc_status=0
		wf.append("transitions", {
			"state": from_state, "action": "Cancel", "next_state": "Rejected",
			"allowed": "Finance Controller", "allow_self_approval": 1,
		})
	for from_state in ["Approved Level 2", "Released"]:  # doc_status=1
		wf.append("transitions", {
			"state": from_state, "action": "Cancel", "next_state": "Cancelled",
			"allowed": "Finance Controller", "allow_self_approval": 1,
		})
	# Jithin 2026-05-23 (AVLTD-01528): cancelling a Rejected PRF used to
	# leave the state as "Rejected" because no transition existed from
	# Rejected. Adding Rejected → Cancel → "Cancelled (Rejected)" —
	# routes to the doc_status=0 sibling because Frappe's workflow
	# engine forbids 0→2 directly (Workflow.validate_docstatus throws
	# "Cannot cancel before submitting"). Visible label still contains
	# "Cancelled" so list/report filters searching for "Cancelled"
	# catch both this and the post-submit Cancelled state.
	wf.append("transitions", {
		"state": "Rejected", "action": "Cancel", "next_state": "Cancelled (Rejected)",
		"allowed": "Finance Controller", "allow_self_approval": 1,
	})

	wf.insert(ignore_permissions=True)
	frappe.db.commit()
	print(f"[{WORKFLOW_NAME}] Workflow created with {len(wf.states)} states and {len(wf.transitions)} transitions")
