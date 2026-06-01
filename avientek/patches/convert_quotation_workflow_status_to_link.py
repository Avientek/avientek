"""Convert Quotation `workflow_status` Custom Field from Data to Link.

Sridhar 2026-06-01: The mirror field surfaced in the filter typeahead as
'Workflow State' but the value input was a free-text box — users wanted
the same dropdown the original auto-injected Link gave them.

Switching fieldtype Data → Link with options="Workflow State" makes the
filter render an autocomplete dropdown of valid workflow state values,
identical UX to the original Frappe-injected field. Verified all
distinct `tabQuotation.workflow_state` values have matching `tabWorkflow
State` rows, so existing data passes Link validation.

Idempotent.
"""

import frappe


def execute():
	cf_name = "Quotation-workflow_status"
	if not frappe.db.exists("Custom Field", cf_name):
		print(f"[convert_quotation_workflow_status_to_link] {cf_name} missing — skipping")
		return

	frappe.db.set_value(
		"Custom Field",
		cf_name,
		{
			"fieldtype": "Link",
			"options": "Workflow State",
			"label": "Workflow State",
		},
		update_modified=False,
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print("[convert_quotation_workflow_status_to_link] workflow_status is now Link → Workflow State")
