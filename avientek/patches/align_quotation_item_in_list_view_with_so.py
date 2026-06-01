"""Align Quotation Item Report View columns with Sales Order Item.

Sridhar 2026-06-01: the Sales Order Report View shows item-level columns
(Item Name, Source Warehouse, Net Rate, Net Amount, Amount in Company
Currency, ...) per row by default, because Sales Order Item has those
fields flagged in_list_view=1. Quotation Item only has item_code / qty /
rate / amount → users have to manually Pick Columns every time.

Property Setters flip the same fields to in_list_view=1 on Quotation
Item so its Report View defaults match the Sales Order one. Picker /
typeahead behaviour untouched. Idempotent.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


# Quotation Item fieldnames to expose in Report View by default.
# Picked to mirror Sales Order Item's default columns.
FIELDS_TO_EXPOSE = [
	"item_name",          # Item Name (matches SO column)
	"warehouse",          # Source Warehouse (matches SO column)
	"net_rate",           # Net Rate (matches SO column)
	"net_amount",         # Net Amount (matches SO column)
	"base_amount",        # Amount in Company Currency (matches SO column)
	"base_net_amount",    # Net Amount in Company Currency (matches SO column)
]


def execute():
	touched = 0
	for fn in FIELDS_TO_EXPOSE:
		# Confirm the field exists before adding a Property Setter.
		if not frappe.db.exists("DocField", {"parent": "Quotation Item", "fieldname": fn}):
			print(f"[align_quotation_item_in_list_view_with_so] {fn} not on Quotation Item — skipping")
			continue
		make_property_setter(
			"Quotation Item", fn, "in_list_view", "1", "Check",
		)
		touched += 1
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation Item")
	frappe.clear_cache(doctype="Quotation")
	print(f"[align_quotation_item_in_list_view_with_so] {touched} fields now in_list_view=1")
