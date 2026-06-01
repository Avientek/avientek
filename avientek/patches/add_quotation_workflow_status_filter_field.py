"""Add a `workflow_status` Data mirror Custom Field on Quotation.

Sridhar 2026-06-01: After a Frappe v15 update, the auto-injected
`workflow_state` Link field stopped surfacing in the list-view
"+ Add a Filter" typeahead even with `in_standard_filter=1` (typing
"Wor" returns nothing). Mirror the value into a plain Data Custom Field
that the typeahead can always find. The mirror is populated
automatically via `fetch_from = "workflow_state"` on every save
(base_document.set_fetch_from_value) and backfilled here for existing
rows. The follow-up patch `rename_quotation_workflow_status_to_workflow_state`
relabels this field to 'Workflow State' so users see only one filter
chip. Idempotent.
"""

import frappe


def execute():
	if not frappe.db.exists("Custom Field", "Quotation-workflow_status"):
		insert_after = (
			"workflow_state"
			if frappe.db.exists("Custom Field", "Quotation-workflow_state")
			else "naming_series"
		)

		cf = frappe.new_doc("Custom Field")
		cf.dt = "Quotation"
		cf.fieldname = "workflow_status"
		cf.fieldtype = "Data"
		cf.label = "Workflow State"
		cf.fetch_from = "workflow_state"
		cf.read_only = 1
		cf.in_standard_filter = 1
		cf.in_list_view = 0
		cf.allow_on_submit = 1
		cf.no_copy = 1
		cf.hidden = 0
		cf.translatable = 0
		cf.insert_after = insert_after
		cf.description = (
			"Data mirror of workflow_state so the list-view filter "
			"typeahead can find it (Frappe v15 hides the Link field)."
		)
		cf.insert(ignore_permissions=True)
	else:
		frappe.db.set_value(
			"Custom Field",
			"Quotation-workflow_status",
			{
				"fetch_from": "workflow_state",
				"label": "Workflow State",
				"read_only": 1,
				"in_standard_filter": 1,
				"in_list_view": 0,
				"allow_on_submit": 1,
				"no_copy": 1,
				"translatable": 0,
			},
			update_modified=False,
		)

	frappe.db.sql(
		"UPDATE `tabQuotation` SET workflow_status = workflow_state "
		"WHERE workflow_state IS NOT NULL "
		"AND (workflow_status IS NULL OR workflow_status != workflow_state)"
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print("[add_quotation_workflow_status_filter_field] workflow_status mirror ready (label=Workflow State)")
