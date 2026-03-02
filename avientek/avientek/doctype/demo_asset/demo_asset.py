import frappe
from frappe.model.document import Document
from frappe.utils import flt


class DemoAsset(Document):

	def before_save(self):
		self.validate_asset_status()
		self.sync_values_from_asset()

	def validate_asset_status(self):
		"""Warn if the linked ERPNext Asset is not yet Submitted (capitalized)."""
		if not self.asset:
			return
		status, docstatus = frappe.db.get_value("Asset", self.asset, ["status", "docstatus"]) or (None, None)
		if docstatus != 1:
			frappe.throw(
				frappe._("Asset <b>{0}</b> is not yet submitted/capitalized. "
				"Please complete Asset Capitalization before registering it as a Demo Asset.").format(self.asset)
			)
		if status in ("Draft", "In Maintenance", "Scrapped", "Sold"):
			frappe.msgprint(
				frappe._("Warning: Asset <b>{0}</b> has status <b>{1}</b>. "
				"Verify this asset is suitable for demo use.").format(self.asset, status),
				indicator="orange",
				alert=True,
			)

	def sync_values_from_asset(self):
		"""Pull Gross Value, Accumulated Depreciation and Net Asset Value from linked Asset."""
		if not self.asset:
			return

		asset = frappe.get_doc("Asset", self.asset)

		self.gross_asset_value = flt(asset.gross_purchase_amount)
		self.asset_currency = frappe.db.get_value("Company", self.company, "default_currency")

		# Sum accumulated depreciation from all active depreciation schedules
		accum_dep = frappe.db.sql("""
			SELECT COALESCE(SUM(ds.depreciation_amount), 0)
			FROM `tabDepreciation Schedule` ds
			JOIN `tabAsset Finance Book` afb ON afb.name = ds.parent
			WHERE afb.parent = %s
			  AND ds.schedule_date <= CURDATE()
			  AND ds.journal_entry IS NOT NULL
		""", self.asset)[0][0]

		self.accumulated_depreciation = flt(accum_dep)
		self.net_asset_value = flt(self.gross_asset_value) - flt(self.accumulated_depreciation)

		# Track last depreciation date
		last_dep = frappe.db.sql("""
			SELECT MAX(ds.schedule_date)
			FROM `tabDepreciation Schedule` ds
			JOIN `tabAsset Finance Book` afb ON afb.name = ds.parent
			WHERE afb.parent = %s
			  AND ds.journal_entry IS NOT NULL
		""", self.asset)[0][0]

		if last_dep:
			self.last_depreciation_date = last_dep
