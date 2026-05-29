"""Hide Quotation Item.part_number from Report Builder / Pick Columns.

Sridhar 2026-05-29: even after adding the working Quotation-parent
`first_item_part_number` field (label "Part Number"), users still
saw the broken child-table "Part Number" entries under both
"Items (Quotation Item)" and "Service Items (Quotation Item)" in
the Pick Columns dialog. Both are broken because of the Frappe
(parent_doctype, child_doctype) column-resolver collision when two
child tables share the same doctype.

Fix: Property Setter `report_hide=1` on Quotation Item.part_number.
Frappe's report column picker filters out fields with this flag,
so the two broken entries disappear. The form-level part_number
on Quotation Item rows stays editable (report_hide only affects
Report Builder / Pick Columns visibility, not the form).

The clean Quotation-parent "Part Number" field
(`first_item_part_number`) is on the Quotation doctype itself
(not Quotation Item), so it's unaffected and remains visible.

Idempotent.
"""
import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	make_property_setter(
		"Quotation Item", "part_number", "report_hide", "1", "Check",
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation Item")
	print("[hide_quotation_item_part_number_from_picker] Set report_hide=1 on Quotation Item.part_number")
