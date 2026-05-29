"""Add Quotation.first_item_part_number Custom Field + backfill.

Sridhar/Rahul 2026-05-29: the Report View column for Part Number
sourced from a Quotation Item child table collides with itself
(Quotation has two child tables both pointing to Quotation Item).
Renaming labels helps the picker UX but doesn't fix the underlying
column resolver collision — ticking the child-table-sourced Part
Number still renders blank or wrong data.

Workaround: surface ALL items' part_number directly on the
Quotation parent doctype, comma-joined. Users tick this new
Quotation-level field in Pick Columns — no child-table involved,
no collision, always correct.

Computed in a before_save hook (events/quotation.py
`copy_first_item_part_number`). Backfilled here for existing rows.

Fieldtype is Small Text to accommodate quotes with many items.
Fieldname stays `first_item_part_number` for historical
compatibility (the API created it under that name before the
fieldtype was switched). The hook joins ALL items' part numbers
with comma, deduped, preserving order.

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
		cf.fieldtype = "Small Text"
		cf.read_only = 1
		cf.allow_on_submit = 1
		cf.in_list_view = 0
		cf.in_standard_filter = 0
		cf.insert_after = "title"
		cf.description = (
			"All items' part numbers comma-joined, copied automatically on save. "
			"Use this Quotation-level field in Report View / list view "
			"to avoid the child-table column collision."
		)
		cf.insert(ignore_permissions=True)
		print(f"[add_quotation_first_part_number] Created {FIELD}")
	else:
		# Ensure fieldtype upgraded to Small Text on existing sites
		current_ft = frappe.db.get_value("Custom Field", FIELD, "fieldtype")
		if current_ft != "Small Text":
			frappe.db.set_value(
				"Custom Field", FIELD,
				{"fieldtype": "Small Text",
				 "description": (
					 "All items' part numbers comma-joined, copied automatically on "
					 "save. Use this Quotation-level field in Report View / list view "
					 "to avoid the child-table column collision."
				 )},
				update_modified=False,
			)
			print(f"[add_quotation_first_part_number] Upgraded {FIELD} fieldtype Data → Small Text")

	# Backfill: comma-joined ALL part numbers (deduped, ordered by idx)
	# using GROUP_CONCAT. Rebuild for every Quotation — cheap enough at
	# ~6.7k rows and ensures fresh data after fieldtype change.
	rows = frappe.db.sql(
		"""
		SELECT q.name,
		       GROUP_CONCAT(DISTINCT NULLIF(TRIM(qi.part_number), '') ORDER BY qi.idx SEPARATOR ', ') AS pn_list
		FROM `tabQuotation` q
		INNER JOIN `tabQuotation Item` qi
		  ON qi.parent = q.name
		 AND qi.parentfield = 'items'
		WHERE qi.part_number IS NOT NULL AND TRIM(qi.part_number) != ''
		GROUP BY q.name
		""",
		as_dict=True,
	)
	updated = 0
	for r in rows:
		new_val = r.get("pn_list") or ""
		current = frappe.db.get_value("Quotation", r["name"], "first_item_part_number") or ""
		if current != new_val:
			frappe.db.set_value(
				"Quotation", r["name"], "first_item_part_number", new_val,
				update_modified=False,
			)
			updated += 1
	if rows:
		frappe.db.commit()
	print(f"[add_quotation_first_part_number] Backfill complete — {updated}/{len(rows)} Quotations updated")
