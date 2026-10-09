"""PRF: requester submits for authorisation before authorisers see it.

Jithin 2026-10-09 (WhatsApp, after the Logistics Manager card fix):
authorisers (Accounts User/Manager, Dept Head, Logistics Manager) should see
a PRF only after the requester has finished it and submitted it — not while
it is still a Draft being filled in. Agreed with Sammish: all PRFs, and the
PRFs already in Draft move to the new state (today Draft already means
"waiting for authorisation").

New flow:
  Draft --Submit for Authorisation (requester)--> Pending Authorisation
  Pending Authorisation --Authorise (same roles as before)--> Authorised
  Pending Authorisation --Send Back (authorisers)--> Draft

`create_payment_request_workflow` is run-once (patches.txt), so this bridge
patch changes the live workflow. Idempotent — safe to re-run.
"""
import frappe

WORKFLOW = "Payment Request Form Approval"
DRAFT = "Draft"
PENDING = "Pending Authorisation"
SUBMIT_ACTION = "Submit for Authorisation"
SEND_BACK_ACTION = "Send Back"
AUTHORISE_ACTION = "Authorise"

# Who may edit a PRF while it waits for authorisation (the authorisers +
# finance/admin). The requester no longer edits it; an authoriser sends it
# back to Draft for corrections.
PENDING_EDIT_ROLES = (
	"Accounts User", "Accounts Manager", "Dept Head", "Logistics Manager",
	"Finance Manager", "System Manager",
)


def execute():
	if not frappe.db.exists("Workflow", WORKFLOW):
		return

	if not frappe.db.exists("Workflow State", PENDING):
		frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": PENDING,
						"style": "Warning"}).insert(ignore_permissions=True)
	for action in (SUBMIT_ACTION, SEND_BACK_ACTION):
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master",
							"workflow_action_name": action}).insert(ignore_permissions=True)

	wf = frappe.get_doc("Workflow", WORKFLOW)

	have_states = {(s.state, s.allow_edit) for s in wf.states}
	for role in PENDING_EDIT_ROLES:
		if frappe.db.exists("Role", role) and (PENDING, role) not in have_states:
			wf.append("states", {"state": PENDING, "doc_status": "0", "allow_edit": role})

	# Authorise now starts from Pending Authorisation instead of Draft.
	authoriser_roles = []
	for t in wf.transitions:
		if t.action == AUTHORISE_ACTION and t.state in (DRAFT, PENDING):
			t.state = PENDING
			authoriser_roles.append(t.allowed)

	have = {(t.state, t.action, t.allowed) for t in wf.transitions}
	if (DRAFT, SUBMIT_ACTION, "All") not in have:
		# The requester fires this on their own PRF, so self-approval must be
		# allowed here (enforce_no_self_approval exempts this action).
		wf.append("transitions", {"state": DRAFT, "action": SUBMIT_ACTION,
								  "next_state": PENDING, "allowed": "All",
								  "allow_self_approval": 1})
	for role in authoriser_roles:
		if (PENDING, SEND_BACK_ACTION, role) not in have:
			wf.append("transitions", {"state": PENDING, "action": SEND_BACK_ACTION,
									  "next_state": DRAFT, "allowed": role,
									  "allow_self_approval": 0})

	wf.save(ignore_permissions=True)

	# Existing Drafts were already waiting for authorisation.
	moved = frappe.db.sql(
		"""UPDATE `tabPayment Request Form` SET workflow_state = %s
		   WHERE docstatus = 0 AND workflow_state = %s""",
		(PENDING, DRAFT),
	)
	frappe.db.set_value("Number Card", "PRF Pending Authorization", "filters_json",
						'[["Payment Request Form","workflow_state","=","Pending Authorisation"]]')
	frappe.db.commit()
	print(f"[add_prf_pending_authorisation_state] workflow updated; Drafts moved to {PENDING}")
