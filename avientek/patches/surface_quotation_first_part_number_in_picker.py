"""Surface the Quotation parent-level Part Number mirror in Pick Columns.

Sridhar 2026-06-01: in Report View, ticking 'Items (Quotation Item) →
Part Number' produces blank cells because Frappe's report column resolver
can't disambiguate two child tables (`items` and `custom_service_items`)
that share the same Quotation Item doctype — they collide on the
qb.parentfield-less JOIN and return wrong/empty values.

The parent-level mirror `first_item_part_number` (built by the
before_save hook with the comma-joined items[].part_number) was created
as hidden=1, which kept it out of Pick Columns (Frappe v15
report_view.js filters out hidden fields from the picker).

Unhide it (keep read_only=1) and re-park it on the More Info tab so
users can tick 'Quotation → Part Number' in Pick Columns and get the
joined value cleanly. The form display is a small read-only Data row
that's only visible inside the More Info tab — no clutter on the main
Details tab. Idempotent.
"""

import frappe


CF_NAME = "Quotation-first_item_part_number"


def execute():
	if not frappe.db.exists("Custom Field", CF_NAME):
		print(f"[surface_quotation_first_part_number_in_picker] {CF_NAME} missing — skipping")
		return

	# Try to park it after a stable field inside the More Info tab so it
	# doesn't intrude on the main Details tab.
	preferred_insert_after = "more_info_tab"
	for candidate in ("more_info_tab", "campaign", "source", "territory"):
		if frappe.db.exists(
			"DocField", {"parent": "Quotation", "fieldname": candidate}
		) or frappe.db.exists(
			"Custom Field", {"dt": "Quotation", "fieldname": candidate}
		):
			preferred_insert_after = candidate
			break

	frappe.db.set_value(
		"Custom Field",
		CF_NAME,
		{
			"hidden": 0,
			"read_only": 1,
			"label": "Part Number",
			"insert_after": preferred_insert_after,
			"description": (
				"Read-only mirror of item Part Numbers (comma-joined) — "
				"pick this in Report View 'Pick Columns' to see part "
				"numbers in the report grid."
			),
		},
		update_modified=False,
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print(
		f"[surface_quotation_first_part_number_in_picker] unhidden, "
		f"re-parked after '{preferred_insert_after}'"
	)
