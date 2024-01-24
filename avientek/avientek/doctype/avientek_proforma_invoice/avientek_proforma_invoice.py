# Copyright (c) 2023, Craft and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

class AvientekProformaInvoice(Document):
	def validate(self):
		if self.items:
			self.total = sum(float(i.amount) for i in self.items)