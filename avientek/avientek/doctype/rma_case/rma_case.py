import frappe
from frappe.model.document import Document
from frappe.utils import today, flt, now


class RMACase(Document):

	def validate(self):
		if self.standby_unit and self.demo_asset and self.standby_unit == self.demo_asset:
			frappe.throw("Standby Unit cannot be the same as the Faulty Unit.")

	def before_save(self):
		self.sync_asset_values()
		self.auto_close_date()

	def on_submit(self):
		"""On submit, issue standby unit if assigned."""
		if self.standby_unit:
			frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Issued as Standby")

	def on_cancel(self):
		"""On cancel, free the standby unit."""
		if self.standby_unit:
			frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Free")

	def on_update_after_submit(self):
		"""Allow status changes and standby unit updates after submit."""
		self.auto_close_date()
		self._sync_standby_status()

	def sync_asset_values(self):
		"""Pull financial values from linked Asset."""
		if not self.demo_asset:
			return
		a = frappe.db.get_value("Asset", self.demo_asset, [
			"gross_purchase_amount", "value_after_depreciation", "company",
		], as_dict=True)
		if a:
			self.gross_asset_value = flt(a.gross_purchase_amount)
			self.net_asset_value = flt(a.value_after_depreciation)
			self.accumulated_depreciation = flt(a.gross_purchase_amount) - flt(a.value_after_depreciation)
			if a.company:
				currency = frappe.db.get_value("Company", a.company, "default_currency")
				self.asset_currency = currency or "AED"

	def auto_close_date(self):
		"""Set closed_date when status moves to Closed/Cancelled."""
		if self.status in ("Closed", "Cancelled") and not self.closed_date:
			self.closed_date = today()
		elif self.status not in ("Closed", "Cancelled"):
			self.closed_date = None

	def _sync_standby_status(self):
		"""Update standby unit Asset status based on RMA case changes."""
		old_doc = self.get_doc_before_save()
		old_standby = old_doc.standby_unit if old_doc else None

		# Standby was returned (cleared)
		if old_standby and not self.standby_unit:
			frappe.db.set_value("Asset", old_standby, "custom_dam_status", "Free")
			return

		# Standby was swapped to a different asset
		if old_standby and self.standby_unit and old_standby != self.standby_unit:
			frappe.db.set_value("Asset", old_standby, "custom_dam_status", "Free")
			frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Issued as Standby")
			return

		# Standby exists — sync based on RMA status
		if self.standby_unit:
			if self.status in ("Closed", "Cancelled", "Replaced"):
				frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Free")
			else:
				current = frappe.db.get_value("Asset", self.standby_unit, "custom_dam_status")
				if current in ("Free", None, ""):
					frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Issued as Standby")

	def add_log(self, log_type, description):
		"""Append an entry to the Case Log child table."""
		self.append("case_log", {
			"log_date": now(),
			"log_type": log_type,
			"logged_by": frappe.session.user,
			"description": description,
		})
