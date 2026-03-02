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
			self._set_asset_status("Free", self.current_location or "")

	def on_cancel(self):
		# Revert asset status to Free on cancellation
		self._set_asset_status("Free", "")
		if self.movement_type == "Return":
			# Re-open the previous move-out movement
			self._reopen_previous_movement()

	def _set_asset_status(self, status, location):
		frappe.db.set_value("Demo Asset", self.demo_asset, {
			"status": status,
			"current_location": location,
		})
		frappe.db.commit()

	def _record_return(self):
		frappe.db.set_value("Demo Asset", self.demo_asset, {
			"status": "Free",
			"current_location": "Main Warehouse",
		})

		# Close the matching open Move Out movement
		open_move = frappe.db.get_value("Demo Movement", {
			"demo_asset": self.demo_asset,
			"movement_type": "Move Out",
			"status": ["in", ["Open", "Overdue"]],
			"docstatus": 1,
		}, "name")

		if open_move:
			frappe.db.set_value("Demo Movement", open_move, {
				"status": "Returned",
				"actual_return_date": today(),
			})

	def _reopen_previous_movement(self):
		"""On cancel of Return, revert the matched move-out back to Open/Overdue."""
		prev = frappe.db.get_value("Demo Movement", {
			"demo_asset": self.demo_asset,
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
