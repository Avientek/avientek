# Copyright (c) 2023, Craft and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import money_in_words


class AvientekProformaInvoice(Document):
	def validate(self):
		if self.items:
			self.total = sum(float(i.amount) for i in self.items)
		if self.total_taxes_and_charges or self.total:
			self.grand_total = self.total + self.total_taxes_and_charges
		if self.total:
			self.net_total = self.total
		amount_in_words = money_in_words(self.grand_total)
		self.in_words = amount_in_words