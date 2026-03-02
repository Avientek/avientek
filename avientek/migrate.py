from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def after_migrate():
	make_property_setter(
		"Item", None, "search_fields", "item_name,description,item_group,customer_code,part_number", "Data", for_doctype="Doctype"
	)
	_create_asset_dam_fields()


def _create_asset_dam_fields():
	"""Add Demo Asset Management custom fields to the standard ERPNext Asset doctype."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	fields = [
		{
			"dt": "Asset",
			"fieldname": "custom_dam_section",
			"fieldtype": "Section Break",
			"label": "Demo Asset Management",
			"insert_after": "gross_purchase_amount",
			"collapsible": 1,
		},
		{
			"dt": "Asset",
			"fieldname": "custom_is_demo_asset",
			"fieldtype": "Check",
			"label": "Is Demo Asset",
			"description": "Mark if this asset is designated for demo purposes",
			"insert_after": "custom_dam_section",
			"in_standard_filter": 1,
		},
		{
			"dt": "Asset",
			"fieldname": "custom_dam_status",
			"fieldtype": "Select",
			"label": "Demo Status",
			"options": "\nFree\nOn Demo\nIssued as Standby",
			"default": "Free",
			"read_only": 1,
			"insert_after": "custom_is_demo_asset",
			"in_standard_filter": 1,
			"depends_on": "eval:doc.custom_is_demo_asset",
		},
		{
			"dt": "Asset",
			"fieldname": "custom_dam_customer",
			"fieldtype": "Link",
			"label": "Current Demo Customer",
			"options": "Customer",
			"read_only": 1,
			"insert_after": "custom_dam_status",
			"depends_on": "eval:doc.custom_is_demo_asset",
		},
	]

	for f in fields:
		fieldname = f["fieldname"]
		dt = f["dt"]
		if not frappe.db.exists("Custom Field", f"{dt}-{fieldname}"):
			create_custom_field(dt, f)
