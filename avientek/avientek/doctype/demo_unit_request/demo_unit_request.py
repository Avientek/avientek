# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class DemoUnitRequest(Document):
	def before_submit(self):
		self.status = "Approved"

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def on_update_after_submit(self):
		if self.status == "Fulfilled" and self.docstatus == 1:
			pass  # allow status update to Fulfilled
		elif self.status == "Rejected" and self.docstatus == 1:
			pass  # allow status update to Rejected

	@frappe.whitelist()
	def set_fulfilled(self):
		if self.docstatus != 1:
			frappe.throw(_("Only submitted requests can be marked as fulfilled"))
		self.db_set("status", "Fulfilled")

	@frappe.whitelist()
	def set_rejected(self):
		if self.docstatus != 1:
			frappe.throw(_("Only submitted requests can be rejected"))
		self.db_set("status", "Rejected")


@frappe.whitelist()
def get_available_demo_assets(item_code, company=None):
	"""Return demo assets that match or are similar to the given stock item.

	Matches by:
	1. Assets whose asset_name equals the item's item_name (created via Asset Capitalization)
	2. Assets whose custom_part_no equals the item's part number
	"""
	if not item_code:
		return []

	item = frappe.get_cached_doc("Item", item_code)
	item_name = item.item_name
	part_number = item.get("part_number") or ""

	# Build OR conditions to find matching demo assets
	conditions = ["a.custom_is_demo_asset = 1", "a.docstatus = 1"]
	or_parts = []
	values = {}

	if item_name:
		or_parts.append("a.asset_name = %(item_name)s")
		values["item_name"] = item_name

	if part_number:
		or_parts.append("a.custom_part_no = %(part_number)s")
		values["part_number"] = part_number

	if not or_parts:
		return []

	conditions.append(f"({' OR '.join(or_parts)})")

	if company:
		conditions.append("a.company = %(company)s")
		values["company"] = company

	where = " AND ".join(conditions)

	assets = frappe.db.sql(f"""
		SELECT
			a.name,
			a.asset_name,
			a.custom_dam_status,
			a.custom_part_no,
			a.location,
			a.custom_dam_customer,
			a.custom_dam_country,
			a.company,
			a.status
		FROM `tabAsset` a
		WHERE {where}
		ORDER BY
			FIELD(a.custom_dam_status, 'Free', 'Issued as Standby', 'On Demo') ASC,
			a.name ASC
	""", values, as_dict=True)

	return assets
