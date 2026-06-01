"""Split Quotation Part Number mirror into Item / Optional Item columns.

Sridhar 2026-06-01: the existing `first_item_part_number` parent field
joined ALL items[] part numbers into one column labelled 'Part Number'.
Customer wants the same treatment for `custom_service_items` (Optional
Items) so Report View can show item part numbers and optional-item part
numbers in distinct columns.

This patch:
  1. Relabels existing `first_item_part_number` → 'Item Part Number'.
  2. Creates new `optional_item_part_numbers` Custom Field (Small Text,
     hidden=0, read_only=1) on Quotation, parked right after the Item
     Part Number field on the More Info tab.
  3. Backfills both fields for existing rows via subquery (DB-side
     GROUP_CONCAT) so the columns aren't empty until each Quotation is
     re-saved.

The hook `avientek.events.quotation.copy_first_item_part_number` now
populates BOTH fields on every save. Idempotent.
"""

import frappe


ITEM_CF = "Quotation-first_item_part_number"
OPT_CF = "Quotation-optional_item_part_numbers"


def execute():
	# 1. Relabel existing item-part-number field
	if frappe.db.exists("Custom Field", ITEM_CF):
		frappe.db.set_value(
			"Custom Field",
			ITEM_CF,
			{"label": "Item Part Number"},
			update_modified=False,
		)
		print(f"[add_quotation_optional_item_part_numbers] {ITEM_CF} relabelled to 'Item Part Number'")

	# 2. Create the optional-item-part-numbers mirror
	if not frappe.db.exists("Custom Field", OPT_CF):
		cf = frappe.new_doc("Custom Field")
		cf.dt = "Quotation"
		cf.fieldname = "optional_item_part_numbers"
		cf.label = "Optional Item Part Number"
		cf.fieldtype = "Small Text"
		cf.read_only = 1
		cf.hidden = 0
		cf.no_copy = 1
		cf.translatable = 0
		cf.insert_after = "first_item_part_number"
		cf.description = (
			"Read-only mirror of Optional Items' Part Numbers "
			"(comma-joined) — pick this in Report View 'Pick Columns' to "
			"see optional-item part numbers in the report grid."
		)
		cf.insert(ignore_permissions=True)
		print(f"[add_quotation_optional_item_part_numbers] created {OPT_CF}")
	else:
		frappe.db.set_value(
			"Custom Field",
			OPT_CF,
			{
				"label": "Optional Item Part Number",
				"fieldtype": "Small Text",
				"read_only": 1,
				"hidden": 0,
				"no_copy": 1,
				"translatable": 0,
				"insert_after": "first_item_part_number",
			},
			update_modified=False,
		)

	# 3. Backfill both columns from each Quotation's child rows.
	frappe.db.sql("""
		UPDATE `tabQuotation` q
		LEFT JOIN (
			SELECT parent, GROUP_CONCAT(DISTINCT NULLIF(TRIM(part_number), '') ORDER BY idx SEPARATOR ', ') AS pn
			FROM `tabQuotation Item`
			WHERE parenttype = 'Quotation' AND parentfield = 'items'
			GROUP BY parent
		) i ON i.parent = q.name
		LEFT JOIN (
			SELECT parent, GROUP_CONCAT(DISTINCT NULLIF(TRIM(part_number), '') ORDER BY idx SEPARATOR ', ') AS pn
			FROM `tabQuotation Item`
			WHERE parenttype = 'Quotation' AND parentfield = 'custom_service_items'
			GROUP BY parent
		) s ON s.parent = q.name
		SET q.first_item_part_number = COALESCE(i.pn, ''),
		    q.optional_item_part_numbers = COALESCE(s.pn, '')
	""")
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print("[add_quotation_optional_item_part_numbers] backfilled both Part Number columns")
