"""Rahul 2026-10-13 (Project module, points 1 & 2). Idempotent.

1. Users could not edit projects: the 2025 "Project Workflow" (an events /
   webinar approval chain: Event Coordinator -> Project Lead -> Webinar Head ->
   Events Head) was still active on Project. Every project sat in its Draft
   state, where only Event Coordinator / Project Lead may edit, so Projects
   Users and Sales Support saw the form frozen. No project ever moved past
   Draft. Project approval is now handled by custom_project_status plus the
   Project L2 Approver gate (avientek.events.project.enforce_l2_approval), so
   the old workflow is switched off (kept, not deleted).

2. Project Status becomes mandatory (migrate.py). Existing projects with a
   blank status, or the retired "Discussion" value (removed from the options
   on 2026-08-25), are set to "Open". Written directly so old projects are
   not re-validated.
"""
import frappe

_OLD_WORKFLOW = "Project Workflow"


def execute():
	if frappe.db.get_value("Workflow", _OLD_WORKFLOW, "is_active"):
		frappe.db.set_value("Workflow", _OLD_WORKFLOW, "is_active", 0)
		frappe.clear_cache(doctype="Project")

	if frappe.db.has_column("Project", "custom_project_status"):
		frappe.db.sql(
			"""UPDATE `tabProject`
			   SET custom_project_status = 'Open'
			   WHERE IFNULL(custom_project_status, '') IN ('', 'Discussion')"""
		)
