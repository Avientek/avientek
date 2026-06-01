"""Rename the Quotation workflow_status mirror to display as 'Workflow State'.

Sridhar 2026-06-01: After the earlier `add_quotation_workflow_status_filter_field`
ran on local + prod, the Quotation list view shows two standard filter chips:
'Workflow State' (the auto-injected Link, marked in_standard_filter=1 by the
earlier `enable_quotation_workflow_state_filter` patch) and 'Workflow Status'
(the new Data mirror). Sridhar wants ONE chip, labelled 'Workflow State'.

This patch:

1. Relabels Custom Field `Quotation-workflow_status` from 'Workflow Status'
   to 'Workflow State', so the chip and typeahead show the expected name.
2. Drops the duplicate Property Setter on `Quotation.workflow_state` so the
   Link variant stops appearing as a separate chip. The Link itself stays
   (auto-injected by the workflow) — it just won't render as a standard
   filter pill.

After this, the user sees one 'Workflow State' chip + one 'Workflow State'
typeahead match, both backed by the Data mirror that always works regardless
of Frappe v15 typeahead quirks. Idempotent.
"""

import frappe


def execute():
	cf_name = "Quotation-workflow_status"
	if frappe.db.exists("Custom Field", cf_name):
		frappe.db.set_value(
			"Custom Field",
			cf_name,
			"label",
			"Workflow State",
			update_modified=False,
		)
		print(f"[rename_quotation_workflow_status_to_workflow_state] relabelled {cf_name}")

	# Drop the duplicate chip on the auto-injected workflow_state Link.
	ps_filters = {
		"doc_type": "Quotation",
		"field_name": "workflow_state",
		"property": "in_standard_filter",
	}
	dupes = frappe.get_all("Property Setter", filters=ps_filters, pluck="name")
	for ps in dupes:
		frappe.delete_doc("Property Setter", ps, ignore_permissions=True, force=True)
		print(f"[rename_quotation_workflow_status_to_workflow_state] removed Property Setter {ps}")

	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
