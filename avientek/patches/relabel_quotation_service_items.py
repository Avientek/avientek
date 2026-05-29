"""Relabel Quotation Custom Field `custom_service_items` from
"Optional Items" to "Service Items" to resolve a Report View column
collision.

Sridhar/Rahul 2026-05-29: the Report View Pick Columns dialog showed
two entries called "Part Number (Quotation Item)" because Quotation
has two child tables both pointing to `Quotation Item`:

    items                  Items           Quotation Item  (standard)
    custom_service_items   Optional Items  Quotation Item  (avientek)

Frappe's column resolver keys on (parent_doctype, child_doctype) so
both collide. Ticking either "Part Number" rendered data from the
wrong table — Sridhar saw real part numbers under "Optional Items"
even when his quotes had zero rows in custom_service_items.

Fix: rename the LABEL only (fieldname stays). All 6 code references
across hooks.py, migrate.py, quotation.js, events/utils.py,
events/sales_order.py, and fixtures use the fieldname — zero
functional impact. UI dropdown now shows "Service Items (Quotation
Item)" distinct from "Items (Quotation Item)".

Property Setter is the canonical way to override a Custom Field's
label, so this patch creates / updates one.

Idempotent.
"""
import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	field = "custom_service_items"
	if not frappe.db.exists("Custom Field", f"Quotation-{field}"):
		print(f"[relabel_quotation_service_items] Custom Field missing — skip")
		return

	# Property Setter for label override survives across migrate runs
	make_property_setter(
		"Quotation", field, "label", "Service Items", "Data",
	)

	# Also update the Custom Field row directly so the change shows up
	# immediately without needing a clear_cache cycle.
	frappe.db.set_value(
		"Custom Field", f"Quotation-{field}", "label", "Service Items",
		update_modified=False,
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print(f"[relabel_quotation_service_items] Renamed label to 'Service Items'")
