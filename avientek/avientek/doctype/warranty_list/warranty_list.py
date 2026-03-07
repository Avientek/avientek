# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import today, date_diff, getdate


class WarrantyList(frappe.model.document.Document):
	def validate(self):
		self.update_days_remaining()

	def before_submit(self):
		self.update_days_remaining()
		if self.warranty_end_date and getdate(self.warranty_end_date) < getdate(today()):
			self.status = "Expired"
		else:
			self.status = "Under Warranty"

	def on_update_after_submit(self):
		self.update_days_remaining()

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def update_days_remaining(self):
		if self.warranty_end_date:
			self.days_remaining = date_diff(self.warranty_end_date, today())
