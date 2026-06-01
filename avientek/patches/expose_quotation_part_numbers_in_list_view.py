"""Surface Quotation Part Number mirrors in default Report View columns.

Sridhar 2026-06-01: Report View doesn't show Part Number by default —
users have to Pick Columns every time. Flip in_list_view=1 on the two
parent-level mirror fields so they appear without manual picking:

  - first_item_part_number       (label 'Item Part Number')
  - optional_item_part_numbers   (label 'Optional Item Part Number')

Idempotent.
"""

import frappe


def execute():
	touched = 0
	for cf_name in ("Quotation-first_item_part_number", "Quotation-optional_item_part_numbers"):
		if not frappe.db.exists("Custom Field", cf_name):
			print(f"[expose_quotation_part_numbers_in_list_view] {cf_name} missing — skipping")
			continue
		frappe.db.set_value(
			"Custom Field", cf_name,
			{"in_list_view": 1},
			update_modified=False,
		)
		touched += 1
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print(f"[expose_quotation_part_numbers_in_list_view] {touched} fields now in_list_view=1")
