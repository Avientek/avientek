import frappe
from frappe.model.document import Document
from frappe.utils import today, flt, now


class RMACase(Document):

	def before_save(self):
		self.sync_asset_values()
		self.auto_close_date()

	def sync_asset_values(self):
		"""Pull financial values from linked Asset."""
		if not self.demo_asset:
			return
		a = frappe.db.get_value("Asset", self.demo_asset, [
			"gross_purchase_amount", "asset_value", "asset_serial_no", "company",
		], as_dict=True)
		if a:
			self.gross_asset_value = flt(a.gross_purchase_amount)
			self.net_asset_value = flt(a.asset_value)
			self.accumulated_depreciation = flt(a.gross_purchase_amount) - flt(a.asset_value)
			# Get currency from company
			if a.company:
				currency = frappe.db.get_value("Company", a.company, "default_currency")
				self.asset_currency = currency or "AED"
			if not self.asset_serial_number and a.asset_serial_no:
				self.asset_serial_number = a.asset_serial_no

	def auto_close_date(self):
		"""Set closed_date when status moves to Closed/Cancelled."""
		if self.status in ("Closed", "Cancelled") and not self.closed_date:
			self.closed_date = today()
		elif self.status not in ("Closed", "Cancelled"):
			self.closed_date = None

	def add_log(self, log_type, description):
		"""Append an entry to the Case Log child table."""
		self.append("case_log", {
			"log_date": now(),
			"log_type": log_type,
			"logged_by": frappe.session.user,
			"description": description,
		})

	def on_update(self):
		"""If standby unit is issued, update its custom DAM status on Asset."""
		if self.standby_unit:
			current_status = frappe.db.get_value("Asset", self.standby_unit, "custom_dam_status")
			if self.status in ("Closed", "Cancelled", "Replaced"):
				if current_status == "Issued as Standby":
					frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Free")
			else:
				if current_status in ("Free", None, ""):
					frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Issued as Standby")
