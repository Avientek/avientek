# Copyright (c) 2023, Craft and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import money_in_words


class AvientekProformaInvoice(Document):
	def validate(self):
		if self.items:
			self.total = sum(float(i.amount) for i in self.items)
		if self.total_taxes_and_charges or self.total or self.discount_amount:
			self.grand_total = self.total + self.total_taxes_and_charges
		if self.total and self.sales_texes_and_charges:
			total_taxes_charges = 0
			for i in self.sales_texes_and_charges:
				tax_amount = (i.rate/100)*self.total
				total_amount = tax_amount + self.total
				i.tax_amount = tax_amount
				i.total = total_amount
				total_taxes_charges = total_taxes_charges + i.tax_amount
			self.total_taxes_and_charges = total_taxes_charges

		self.net_total = self.total - (self.discount_amount if self.discount_amount else 0)

		amount_in_words = money_in_words(self.grand_total)
		self.in_words = amount_in_words
		field_map = {
			"Grand Total": "grand_total",
			"Net Total": "net_total"
		}
		if self.additional_discount_percentage:
			discount_percentage = self.additional_discount_percentage / 100
			self.discount_amount = discount_percentage * self.get(field_map[self.apply_discount_on])

		self.grand_total -= self.discount_amount if self.discount_amount else 0