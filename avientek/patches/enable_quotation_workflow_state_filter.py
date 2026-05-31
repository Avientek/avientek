"""Enable Quotation.workflow_state as a standard list-view filter.

Sridhar 2026-05-30: users couldn't filter Quotation list by workflow
state — typing "Wor" in the filter dropdown showed nothing. Frappe
auto-injects workflow_state when a workflow is attached, but doesn't
flag it as `in_standard_filter`, so it stays hidden from the filter
chip dropdown unless manually added each time.

Property Setter `in_standard_filter=1` makes it appear as a default
filter chip alongside Status / Date / Order Type / Party.

Idempotent — make_property_setter overwrites the existing row with the
same property name.
"""
import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	make_property_setter(
		"Quotation", "workflow_state", "in_standard_filter", "1", "Check",
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print("[enable_quotation_workflow_state_filter] in_standard_filter=1 set on Quotation.workflow_state")
