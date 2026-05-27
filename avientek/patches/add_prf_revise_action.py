"""Add 'Revise' workflow action on PRF Authorised state (Sridhar 2026-05-27).

Approver on a PRF in 'Authorised' state currently only has Approve / Reject / Cancel.
Reject is final (stigma); Cancel routes to 'Rejected' (misleading). There's no way to
send the doc back to the creator for corrections.

Adds a new 'Revise' transition: Authorised → Draft. Roles are read from
Avientek Settings → PRF Revise Roles (multi-role table, same pattern as
quote_approver_roles). Defaults to Finance Manager + General Manager +
Director when the table is empty.

Also ensures:
- Workflow Action Master 'Revise' exists
- Custom Field PRF.revise_reason exists (Long Text, allow_on_submit=1 not
  needed since Authorised is doc_status=0)
- Default roles seeded in prf_revise_roles when empty
- Existing duplicate/stale Revise transitions on Authorised are removed
  first so re-running is safe

Idempotent — safe to re-run after seeder changes.
"""
import frappe


WORKFLOW = "Payment Request Form Approval"
SOURCE_STATE = "Authorised"
ACTION = "Revise"
TARGET_STATE = "Draft"
DEFAULT_ROLES = ["Finance Manager", "General Manager", "Director"]


def execute():
	if not frappe.db.exists("Workflow", WORKFLOW):
		print(f"[add_prf_revise_action] {WORKFLOW} not present — skipping")
		return

	# 1. Workflow Action Master 'Revise'
	if not frappe.db.exists("Workflow Action Master", ACTION):
		wam = frappe.new_doc("Workflow Action Master")
		wam.workflow_action_name = ACTION
		wam.insert(ignore_permissions=True)
		print(f"[add_prf_revise_action] Created Workflow Action Master '{ACTION}'")

	# 2. Custom Field PRF.revise_reason
	cf_name = "Payment Request Form-revise_reason"
	if not frappe.db.exists("Custom Field", cf_name):
		cf = frappe.new_doc("Custom Field")
		cf.dt = "Payment Request Form"
		cf.fieldname = "revise_reason"
		cf.fieldtype = "Long Text"
		cf.label = "Revise Reason"
		cf.read_only = 1
		cf.description = (
			"Captured automatically when an approver hits 'Revise' on an "
			"Authorised PRF. Visible to the creator so they know what to fix."
		)
		# Park it under an existing section; insert_after a known field
		cf.insert_after = "additional_documents"
		cf.insert(ignore_permissions=True)
		print(f"[add_prf_revise_action] Created Custom Field '{cf_name}'")

	# 3. Seed default roles in Avientek Settings → prf_revise_roles if empty
	try:
		settings = frappe.get_single("Avientek Settings")
	except Exception:
		settings = None
	if settings and not (settings.get("prf_revise_roles") or []):
		for role in DEFAULT_ROLES:
			if frappe.db.exists("Role", role):
				settings.append("prf_revise_roles", {"role": role})
		settings.save(ignore_permissions=True)
		print(f"[add_prf_revise_action] Seeded prf_revise_roles defaults: {DEFAULT_ROLES}")

	# 4. Compute the roles to apply (settings table OR defaults)
	configured_roles = []
	if settings:
		configured_roles = [r.role for r in (settings.get("prf_revise_roles") or []) if r.get("role")]
	if not configured_roles:
		configured_roles = [r for r in DEFAULT_ROLES if frappe.db.exists("Role", r)]

	# 5. Refresh the workflow's Authorised → Revise → Draft transitions
	wf = frappe.get_doc("Workflow", WORKFLOW)

	# Drop any existing Revise transitions FROM Authorised so we can re-add cleanly
	before = len(wf.transitions or [])
	wf.transitions = [
		t for t in (wf.transitions or [])
		if not (t.state == SOURCE_STATE and t.action == ACTION)
	]
	dropped = before - len(wf.transitions)

	# Append one transition row per configured role (Frappe workflows fan
	# out per-role — Workflow Transition has a single 'allowed' field).
	added = 0
	for role in configured_roles:
		wf.append("transitions", {
			"state": SOURCE_STATE,
			"action": ACTION,
			"next_state": TARGET_STATE,
			"allowed": role,
			"allow_self_approval": 1,
		})
		added += 1

	wf.save(ignore_permissions=True)
	frappe.db.commit()
	print(
		f"[add_prf_revise_action] Workflow updated — dropped {dropped} stale Revise "
		f"transitions, added {added} fresh ones (roles: {configured_roles})"
	)
