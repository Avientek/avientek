"""Expose Brand as a visible column on the Sales Order Items grid.

Sridhar 2026-08-05: Sales Order Item has a `brand` field (Link to Brand),
but ERPNext core ships it with hidden=1 and no in_list_view, so it never
shows as a column in the child table grid — Customize Form's "Hidden"
checkbox alone doesn't add it as a grid column, `in_list_view` does.

Property Setters flip both flags on Sales Order Item so the column
becomes visible without editing core. Idempotent.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	if not frappe.db.exists("DocField", {"parent": "Sales Order Item", "fieldname": "brand"}):
		print("[show_brand_column_in_sales_order_items] brand field not on Sales Order Item — skipping")
		return

	make_property_setter("Sales Order Item", "brand", "hidden", "0", "Check")
	make_property_setter("Sales Order Item", "brand", "in_list_view", "1", "Check")

	frappe.db.commit()
	frappe.clear_cache(doctype="Sales Order Item")
	frappe.clear_cache(doctype="Sales Order")
	print("[show_brand_column_in_sales_order_items] brand column enabled on Sales Order Item")
