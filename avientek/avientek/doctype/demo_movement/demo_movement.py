import frappe
from frappe.model.document import Document
from frappe.utils import date_diff, today


class DemoMovement(Document):

	def validate(self):
		self.calculate_days_outstanding()

	def calculate_days_outstanding(self):
		if self.movement_date and self.movement_type == "Move Out":
			self.days_outstanding = date_diff(today(), self.movement_date)
		elif self.movement_type == "Return":
			self.days_outstanding = 0

	def on_submit(self):
		if self.movement_type == "Move Out":
			self._set_asset_status("On Demo", self.customer)
		elif self.movement_type == "Return":
			self._record_return()
		elif self.movement_type == "Internal Transfer":
			self._set_asset_status("Free", "")

	def on_cancel(self):
		if self.movement_type == "Move Out":
			self._set_asset_status("Free", "")
		elif self.movement_type == "Return":
			self._set_asset_status("Free", "")
			self._reopen_previous_movement()
		elif self.movement_type == "Internal Transfer":
			self._set_asset_status("Free", "")

	def _set_asset_status(self, status, customer):
		frappe.db.set_value("Asset", self.asset, {
			"custom_dam_status": status,
			"custom_dam_customer": customer,
		})
		frappe.db.commit()

	def _record_return(self):
		frappe.db.set_value("Asset", self.asset, {
			"custom_dam_status": "Free",
			"custom_dam_customer": "",
		})

		# Close the matching open Move Out movement
		open_move = frappe.db.get_value("Demo Movement", {
			"asset": self.asset,
			"movement_type": "Move Out",
			"status": ["in", ["Open", "Overdue"]],
			"docstatus": 1,
		}, "name")

		if open_move:
			frappe.db.set_value("Demo Movement", open_move, {
				"status": "Returned",
				"actual_return_date": today(),
			})

		# Mark this Return movement as Completed
		frappe.db.set_value("Demo Movement", self.name, "status", "Completed")

	def _reopen_previous_movement(self):
		"""On cancel of Return, revert the matched move-out back to Open/Overdue."""
		prev = frappe.db.get_value("Demo Movement", {
			"asset": self.asset,
			"movement_type": "Move Out",
			"status": "Returned",
			"docstatus": 1,
		}, ["name", "expected_return_date"], as_dict=True)

		if prev:
			from frappe.utils import getdate
			status = "Overdue" if prev.expected_return_date and getdate(prev.expected_return_date) < getdate(today()) else "Open"
			frappe.db.set_value("Demo Movement", prev.name, {
				"status": status,
				"actual_return_date": None,
			})
