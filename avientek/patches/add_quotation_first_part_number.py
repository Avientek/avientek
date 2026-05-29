"""Add Quotation.first_item_part_number Custom Field + backfill.

Sridhar/Rahul 2026-05-29: the Report View column for Part Number
sourced from a Quotation Item child table collides with itself
(Quotation has two child tables both pointing to Quotation Item).
Renaming labels helps the picker UX but doesn't fix the underlying
column resolver collision — ticking the child-table-sourced Part
Number still renders blank or wrong data.

Workaround: surface the FIRST item's part_number directly on the
Quotation parent doctype. Users tick this new Quotation-level
field in Pick Columns — no child-table involved, no collision,
always correct.

Computed in a before_save hook (events/quotation.py
`copy_first_item_part_number`). Backfilled here for existing rows.

Shows the first row's part_number only; for quotes with multiple
items, only the first item's part number is on the parent. If
business wants a comma-joined list of ALL part numbers, change the
fieldtype to Small Text and update the hook to comma-join.

Idempotent.
"""
import frappe


FIELD = "Quotation-first_item_part_number"


def execute():
	if not frappe.db.exists("Custom Field", FIELD):
		cf = frappe.new_doc("Custom Field")
		cf.dt = "Quotation"
		cf.fieldname = "first_item_part_number"
		cf.label = "Part Number"
		cf.fieldtype = "Data"
		cf.read_only = 1
		cf.allow_on_submit = 1
		cf.in_list_view = 0
		cf.in_standard_filter = 0
		cf.insert_after = "title"
		cf.description = (
			"First item's part number, copied automatically on save. "
			"Use this Quotation-level field in Report View / list view "
			"to avoid the child-table column collision."
		)
		cf.insert(ignore_permissions=True)
		print(f"[add_quotation_first_part_number] Created {FIELD}")

	# Backfill — copy from items[0].part_number for every Quotation
	# where first_item_part_number is empty
	rows = frappe.db.sql(
		"""
		SELECT q.name, qi.part_number
		FROM `tabQuotation` q
		INNER JOIN `tabQuotation Item` qi
		  ON qi.parent = q.name
		 AND qi.parentfield = 'items'
		 AND qi.idx = 1
		WHERE (q.first_item_part_number IS NULL OR q.first_item_part_number = '')
		  AND qi.part_number IS NOT NULL AND qi.part_number != ''
		""",
		as_dict=True,
	)
	for r in rows:
		frappe.db.set_value(
			"Quotation", r["name"], "first_item_part_number", r["part_number"],
			update_modified=False,
		)
	if rows:
		frappe.db.commit()
	print(f"[add_quotation_first_part_number] Backfilled {len(rows)} Quotations")
