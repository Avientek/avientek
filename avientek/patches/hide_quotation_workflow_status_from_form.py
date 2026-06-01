"""Hide Quotation workflow_status mirror from form view, keep in picker.

Sridhar 2026-06-01: the workflow_status mirror Custom Field (Link →
Workflow State, label 'Workflow State') was unhidden earlier so it
surfaces in Pick Columns / filter typeahead. But it now clutters the
Quotation form's Details tab — users see the field + its 'data mirror'
description, which is internal implementation detail.

Solution: depends_on = "eval:0" hides the field from the form view
without affecting picker/typeahead — Frappe's filter and Pick Columns
code paths build their lists from meta but do NOT evaluate depends_on
(that's runtime form rendering). Net result: invisible on form,
visible in Report View Pick Columns and "+ Add a Filter" typeahead.

Idempotent.
"""

import frappe


CF_NAME = "Quotation-workflow_status"


def execute():
	if not frappe.db.exists("Custom Field", CF_NAME):
		print(f"[hide_quotation_workflow_status_from_form] {CF_NAME} missing — skipping")
		return

	frappe.db.set_value(
		"Custom Field",
		CF_NAME,
		{
			"depends_on": "eval:0",
			# Drop the implementation-detail description so it doesn't show
			# anywhere a user might see it.
			"description": "",
		},
		update_modified=False,
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print("[hide_quotation_workflow_status_from_form] hidden from form, kept in picker")
