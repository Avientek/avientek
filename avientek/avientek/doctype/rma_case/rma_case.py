import frappe
from frappe.model.document import Document
from frappe.utils import today, flt, now


class RMACase(Document):

	def before_save(self):
		self.sync_asset_values()
		self.auto_close_date()

	def sync_asset_values(self):
		"""Pull financial values from linked Demo Asset."""
		if not self.demo_asset:
			return
		da = frappe.db.get_value("Demo Asset", self.demo_asset, [
			"gross_asset_value", "accumulated_depreciation",
			"net_asset_value", "asset_currency", "serial_number",
		], as_dict=True)
		if da:
			self.gross_asset_value = flt(da.gross_asset_value)
			self.accumulated_depreciation = flt(da.accumulated_depreciation)
			self.net_asset_value = flt(da.net_asset_value)
			self.asset_currency = da.asset_currency
			if not self.asset_serial_number:
				self.asset_serial_number = da.serial_number

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
		"""If standby unit is issued, update its Demo Asset status."""
		if self.standby_unit:
			current_status = frappe.db.get_value("Demo Asset", self.standby_unit, "status")
			if self.status in ("Closed", "Cancelled", "Replaced"):
				if current_status == "Issued as Standby":
					frappe.db.set_value("Demo Asset", self.standby_unit, "status", "Free")
			else:
				if current_status == "Free":
					frappe.db.set_value("Demo Asset", self.standby_unit, "status", "Issued as Standby")
