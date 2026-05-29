"""Hide Quotation.first_item_part_number Custom Field from the form.

Sridhar 2026-05-29: the Quotation-level Part Number Custom Field
(`first_item_part_number`) was showing on the Quotation form even
though we only need it surfaced in Report View / Pick Columns. The
existing add_quotation_first_part_number patch was updated to set
hidden=1 (commit 16b193e), but that patch is already in tabPatch Log
on existing sites so the update never re-runs on bench migrate.

This is a separate one-shot bridge patch that ensures hidden=1 on
the Custom Field. Pick Columns still surfaces the field (Frappe lists
hidden fields in the picker), so the report use case is preserved.

Idempotent.
"""
import frappe


FIELD = "Quotation-first_item_part_number"


def execute():
	if not frappe.db.exists("Custom Field", FIELD):
		print(f"[hide_quotation_first_part_number_field] {FIELD} not present — skipping")
		return

	current = frappe.db.get_value("Custom Field", FIELD, "hidden")
	if current:
		print(f"[hide_quotation_first_part_number_field] already hidden")
		return

	frappe.db.set_value(
		"Custom Field", FIELD, "hidden", 1,
		update_modified=False,
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print(f"[hide_quotation_first_part_number_field] Set hidden=1 on {FIELD}")
