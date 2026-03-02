import frappe
from frappe.model.document import Document
from frappe.utils import today


class MaterialDispatchNote(Document):

	def validate(self):
		self.validate_items()

	def validate_items(self):
		if not self.items:
			frappe.throw(frappe._("Please add at least one item to dispatch."))
		for row in self.items:
			if not row.qty or row.qty <= 0:
				frappe.throw(frappe._("Row {0}: Qty must be greater than 0.").format(row.idx))

	def on_submit(self):
		self.db_set("status", "Dispatched")

	def on_cancel(self):
		self.db_set("status", "Cancelled")
