"""Revert Quotation Custom Field `custom_service_items` label back to
"Optional Items".

Sridhar 2026-05-29: previously (commit 2bfcab7 / patch
relabel_quotation_service_items) we renamed the label from
"Optional Items" → "Service Items" so the Report View Pick Columns
picker would show distinct labels for the two child tables both
pointing to `Quotation Item` (items + custom_service_items).

Since then:
- Quotation Item.part_number has report_hide=1 (patch
  hide_quotation_item_part_number_from_picker)
- JS dedup hides the broken child-table Part Number entries from
  the Pick Columns dialog (commit 970a6cd)
- The Quotation-parent `first_item_part_number` field is the working
  Part Number column for reports

So the original UX reason for the rename is moot. Sridhar wants the
familiar "Optional Items" label back.

Updates BOTH the Property Setter (which the previous patch created)
AND the Custom Field row itself, so the new label sticks across
clear_cache calls and matches between the schema and the override.

Idempotent.
"""
import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	field = "custom_service_items"
	new_label = "Optional Items"

	if not frappe.db.exists("Custom Field", f"Quotation-{field}"):
		print(f"[relabel_quotation_service_items_back_to_optional] Custom Field missing — skip")
		return

	# Property Setter override
	make_property_setter(
		"Quotation", field, "label", new_label, "Data",
	)

	# Custom Field row label too
	frappe.db.set_value(
		"Custom Field", f"Quotation-{field}", "label", new_label,
		update_modified=False,
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print(f"[relabel_quotation_service_items_back_to_optional] Reverted label to '{new_label}'")
