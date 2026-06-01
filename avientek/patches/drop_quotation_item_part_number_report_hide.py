"""Drop the report_hide=1 Property Setter on Quotation Item.part_number.

Sridhar 2026-06-01: Part Number column was missing from Quotation Report
View even though every user's __UserSettings.Report.fields had
["part_number", "Quotation Item"] saved. Root cause was a leftover
Property Setter `Quotation Item-part_number-report_hide = 1` from the
2026-05-29 column-collision fix (back when both `items` and
`custom_service_items` shared 'Part Number' and Frappe's column
resolver couldn't tell them apart). The MutationObserver in
quotation_list.js now hides those duplicate picker entries directly,
so the global report_hide isn't needed anymore — and it was actively
breaking the user-saved column.

Idempotent.
"""

import frappe


PS_NAME = "Quotation Item-part_number-report_hide"


def execute():
	if frappe.db.exists("Property Setter", PS_NAME):
		frappe.delete_doc(
			"Property Setter", PS_NAME,
			ignore_permissions=True, force=True,
		)
		frappe.db.commit()
		frappe.clear_cache(doctype="Quotation Item")
		frappe.clear_cache(doctype="Quotation")
		print(f"[drop_quotation_item_part_number_report_hide] removed {PS_NAME}")
	else:
		print(f"[drop_quotation_item_part_number_report_hide] {PS_NAME} not present — nothing to do")
