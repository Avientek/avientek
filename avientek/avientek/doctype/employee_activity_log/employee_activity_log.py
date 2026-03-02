import frappe
from frappe.model.document import Document
from frappe.utils import time_diff_in_hours


class EmployeeActivityLog(Document):

	def validate(self):
		self.calculate_duration()

	def calculate_duration(self):
		if self.check_in_time and self.check_out_time:
			try:
				hours = time_diff_in_hours(self.check_out_time, self.check_in_time)
				self.duration_hours = round(float(hours), 2) if hours and hours > 0 else 0
			except Exception:
				self.duration_hours = 0

	def on_submit(self):
		self.db_set("status", "Completed")

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	@frappe.whitelist()
	def approve(self):
		self.db_set({
			"approval_status": "Approved",
			"approved_by": frappe.session.user,
		})
		frappe.msgprint(frappe._("Activity Log approved."), indicator="green", alert=True)

	@frappe.whitelist()
	def reject(self, comments=None):
		self.db_set({
			"approval_status": "Rejected",
			"approved_by": frappe.session.user,
			"approval_comments": comments or "",
		})
		frappe.msgprint(frappe._("Activity Log rejected."), indicator="red", alert=True)
