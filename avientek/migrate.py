from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def after_migrate():
	make_property_setter(
		"Item", None, "search_fields", "item_name,description,item_group,customer_code,part_number", "Data", for_doctype="Doctype"
	)
	_create_asset_dam_fields()
	_deactivate_old_quotation_workflows()
	_fix_quotation_item_calc_layout()
	_fix_global_field_settings()
	_enforce_custom_role_permissions()


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
			"allow_on_submit": 1,
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
		{
			"dt": "Asset",
			"fieldname": "custom_serial_no",
			"fieldtype": "Data",
			"label": "Serial No",
			"insert_after": "custom_dam_customer",
		},
		{
			"dt": "Asset",
			"fieldname": "custom_part_no",
			"fieldtype": "Data",
			"label": "Part No",
			"insert_after": "custom_serial_no",
		},
		{
			"dt": "Asset",
			"fieldname": "custom_dam_country",
			"fieldtype": "Link",
			"label": "Country",
			"options": "Country",
			"insert_after": "custom_owned_by",
		},
		{
			"dt": "Asset",
			"fieldname": "custom_dam_notes",
			"fieldtype": "Small Text",
			"label": "Notes",
			"insert_after": "custom_dam_country",
		},
	]

	for f in fields:
		fieldname = f["fieldname"]
		dt = f["dt"]
		cf_name = f"{dt}-{fieldname}"
		if not frappe.db.exists("Custom Field", cf_name):
			create_custom_field(dt, f)
		else:
			# Patch properties that may have changed after initial creation
			update_vals = {}
			if f.get("allow_on_submit"):
				update_vals["allow_on_submit"] = f["allow_on_submit"]
			# Ensure fieldtype and options stay in sync (e.g. Select → Link)
			if f.get("fieldtype"):
				update_vals["fieldtype"] = f["fieldtype"]
			if "options" in f:
				update_vals["options"] = f["options"]
			if update_vals:
				frappe.db.set_value("Custom Field", cf_name, update_vals)


def _fix_quotation_item_calc_layout():
	"""Ensure correct field ordering for Quotation Item expanded form.

	Runs after fixture sync so idx values aren't overwritten.
	Fixes:
	  - Pre-calc section (Standard Price, Special Price, Shipping Mode)
	  - 4-column calculation section with correct idx ordering
	  - Hides legacy fields and stale column breaks
	"""
	dt = "Quotation Item"

	# ── Create missing column breaks if needed ──
	for cb in [
		{"fieldname": "custom_column_break_calc_3", "insert_after": "custom_transport_value"},
	]:
		if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": cb["fieldname"]}):
			doc = frappe.new_doc("Custom Field")
			doc.dt = dt
			doc.fieldname = cb["fieldname"]
			doc.fieldtype = "Column Break"
			doc.insert_after = cb["insert_after"]
			doc.hidden = 0
			doc.insert()

	# ── Hide legacy fields and stale column breaks ──
	legacy = [
		"levee_per", "levee", "total_levee", "base_levee",
		"processing_charges_per", "processing_charges",
		"total_processing_charges", "base_processing_charges",
		"std_margin_per", "std_margin", "total_std_margin", "base_std_margin",
		"total_shipping", "total_reward", "base_shipping", "base_reward",
		"column_break_37", "column_break_38", "column_break_44",
	]
	for fn in legacy:
		cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fn}, "name")
		if cf:
			frappe.db.set_value("Custom Field", cf, "hidden", 1)

	# ── Full field chain: pre-calc section + 4-column calc section ──
	#
	# IMPORTANT: Standard Quotation Item fields have section/column breaks
	# at idx 35, 41, 51, 53, 55, 58, 60, 65, 68, 70, 73, 75.
	# If our custom fields use idx values in that range, standard breaks
	# interleave and create extra columns/sections in the layout.
	# Solution: start ALL custom fields at idx 100+, safely after all
	# standard fields (which end at idx ~75).
	#
	chain = [
		# Pre-calc section (Standard Price, Special Price, etc.)
		("custom_section_break_dkbzh", "usd_price_list_rate_with_margin"),
		("custom_standard_price_", "custom_section_break_dkbzh"),
		("custom_special_price", "custom_standard_price_"),
		("custom_special_price_note", "custom_special_price"),
		("custom_shipping_mode", "custom_special_price_note"),
		# Calc section: Col 1 — percentages
		("section_break_26", "custom_shipping_mode"),
		("shipping_per", "section_break_26"),
		("reward_per", "shipping_per"),
		("custom_finance_", "reward_per"),
		("custom_transport_", "custom_finance_"),
		# Calc section: Col 2 — values
		("shipping", "custom_transport_"),
		("reward", "shipping"),
		("custom_finance_value", "reward"),
		("custom_transport_value", "custom_finance_value"),
		# Calc section: Col 3 — calculation percentages
		("custom_column_break_calc_3", "custom_transport_value"),
		("custom_incentive_", "custom_column_break_calc_3"),
		("custom_customs_", "custom_incentive_"),
		("custom_markup_", "custom_customs_"),
		("custom_margin_", "custom_markup_"),
		("custom_special_rate", "custom_margin_"),
		("custom_discount_amount_value", "custom_special_rate"),
		("custom_discount_amount_qty", "custom_discount_amount_value"),
		# Calc section: Col 4 — calculation values
		("custom_incentive_value", "custom_discount_amount_qty"),
		("custom_customs_value", "custom_incentive_value"),
		("custom_markup_value", "custom_customs_value"),
		("custom_margin_value", "custom_markup_value"),
		("custom_selling_price", "custom_margin_value"),
		("custom_total_", "custom_selling_price"),
		("custom_cogs", "custom_total_"),
		("custom_addl_discount_amount", "custom_cogs"),
	]

	# Start at idx 100 — safely after ALL standard Quotation Item fields
	# (standard fields end at idx ~75)
	start_idx = 100

	for i, (fieldname, after) in enumerate(chain):
		cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "name")
		if cf:
			frappe.db.set_value("Custom Field", cf, {"idx": start_idx + i, "insert_after": after})

	# Also move hidden legacy fields to idx 200+ so they don't interfere
	legacy_start = 200
	legacy_fields = frappe.db.get_all(
		"Custom Field",
		filters={"dt": dt, "hidden": 1, "fieldname": ["not in", [
			"usd_price_list_rate_with_margin", "tax_rate", "tax_amount", "total_amount",
		]]},
		fields=["name", "fieldname"],
		order_by="idx",
	)
	for j, lf in enumerate(legacy_fields):
		frappe.db.set_value("Custom Field", lf["name"], "idx", legacy_start + j)

	frappe.db.commit()


def _fix_global_field_settings():
	"""Fix field settings that must persist across all servers.

	Runs on every migrate to ensure these settings are always correct,
	regardless of DB state or which server is being migrated.
	"""
	# 1. Hide fields on Quotation / Quotation Item
	hide_fields = [
		("Quotation", "is_reverse_charge"),
		("Quotation Item", "discount_and_margin"),
	]
	for dt, fn in hide_fields:
		has_field = (
			frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fn})
			or frappe.get_meta(dt).has_field(fn)
		)
		if has_field and not frappe.db.exists("Property Setter", {
			"doc_type": dt, "field_name": fn, "property": "hidden"
		}):
			make_property_setter(dt, fn, "hidden", "1", "Check")

	# 2. Make custom_quote_type optional on Sales Invoice and Sales Order
	for dt in ["Sales Invoice", "Sales Order"]:
		cf = frappe.db.exists("Custom Field", f"{dt}-custom_quote_type")
		if cf:
			frappe.db.set_value("Custom Field", cf, "reqd", 0)

	# 3. Set ignore_user_permissions on ALL Quotation custom child tables
	# Prevents "Not permitted" errors for users with Company restrictions
	for fn in ["custom_stock", "custom_brand_summary", "custom_history",
			   "custom_quotation_brand_summary", "custom_service_items",
			   "custom_shipment_and_margin", "optional_items"]:
		cf = frappe.db.exists("Custom Field", f"Quotation-{fn}")
		if cf:
			frappe.db.set_value("Custom Field", cf, "ignore_user_permissions", 1)

	# 3b. Also set ignore_user_permissions on Company Link field INSIDE child DocTypes
	# The parent table field's ignore_user_permissions alone is not enough —
	# Frappe also checks the Link field inside the child table row
	frappe.db.sql("""
		UPDATE tabDocField SET ignore_user_permissions=1
		WHERE parent='Quotation Stock' AND fieldname='company' AND options='Company'
	""")

	# 4. Delete stale column breaks from Quotation Item (permanent cleanup)
	for fn in ["column_break_32", "column_break_38", "custom_column_break_calc_4", "custom_column_break_9d6lj"]:
		cf_name = f"Quotation Item-{fn}"
		if frappe.db.exists("Custom Field", cf_name):
			frappe.delete_doc("Custom Field", cf_name, force=True)

	frappe.db.commit()


def _enforce_custom_role_permissions():
	"""Ensure custom role permissions stay as intended after every migrate.
	Recreates the permission row if it was deleted, and enforces export=0."""
	ROLE = "Sales Invoice- Custom"
	DT = "Sales Invoice"
	EXPECTED = {
		"read": 1, "write": 1, "create": 1, "delete": 0,
		"submit": 1, "cancel": 1, "amend": 1,
		"report": 1, "export": 0, "import": 1,
		"share": 1, "print": 1, "email": 1, "select": 1,
		"if_owner": 0,
	}

	existing = frappe.db.exists("Custom DocPerm", {"parent": DT, "role": ROLE, "permlevel": 0})
	if existing:
		frappe.db.set_value("Custom DocPerm", existing, EXPECTED)
	else:
		# Insert directly via SQL to avoid DocType validation (duplicate role check)
		import frappe.utils
		frappe.db.sql("""
			INSERT INTO `tabCustom DocPerm`
			(name, parent, parentfield, parenttype, role, permlevel,
			 `read`, `write`, `create`, `delete`, submit, cancel, amend,
			 report, export, import, share, print, email, `select`, if_owner,
			 owner, modified_by, creation, modified)
			VALUES (%s, %s, 'permissions', 'DocType', %s, 0,
			 1, 1, 1, 0, 1, 1, 1,
			 1, 0, 1, 1, 1, 1, 1, 0,
			 'Administrator', 'Administrator', %s, %s)
		""", (frappe.generate_hash(length=10), DT, ROLE,
			  frappe.utils.now(), frappe.utils.now()))

	frappe.db.commit()


def _deactivate_old_quotation_workflows():
	"""Deactivate old Quotation workflows when Quotation Final exists."""
	if not frappe.db.exists("Workflow", "Quotation Final"):
		return
	old_workflows = ["Quotation Margin Approval", "Quotation DocFlow", "Quotation"]
	for wf_name in old_workflows:
		if frappe.db.exists("Workflow", wf_name):
			wf = frappe.get_doc("Workflow", wf_name)
			if wf.is_active:
				wf.is_active = 0
				wf.save(ignore_permissions=True)
				frappe.logger().info(f"Deactivated old workflow: {wf_name}")
