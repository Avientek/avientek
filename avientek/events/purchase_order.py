import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt, getdate, nowdate, cint, cstr
from erpnext.controllers.buying_controller import BuyingController
from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder
from erpnext.buying.utils import validate_for_items

class CustomPurchaseOrder(BuyingController):

	def set_incoming_rate(self):
		if self.doctype not in ("Purchase Receipt", "Purchase Invoice", "Purchase Order"):
			return

		ref_doctype_map = {
			"Purchase Order": "Sales Order Item",
			"Purchase Receipt": "Delivery Note Item",
			"Purchase Invoice": "Sales Invoice Item",
		}

		ref_doctype = ref_doctype_map.get(self.doctype)
		items = self.get("items")
		for d in items:
			if not cint(self.get("is_return")):
				# Get outgoing rate based on original item cost based on valuation method

				if not d.get(frappe.scrub(ref_doctype)):
					posting_time = self.get("posting_time")
					if not posting_time and self.doctype == "Purchase Order":
						posting_time = frappe.utils.nowtime()

					outgoing_rate = get_incoming_rate(
						{
							"item_code": d.item_code,
							"warehouse": d.get("from_warehouse"),
							"posting_date": self.get("posting_date") or self.get("transation_date"),
							"posting_time": posting_time,
							"qty": -1 * flt(d.get("stock_qty")),
							"serial_no": d.get("serial_no"),
							"batch_no": d.get("batch_no"),
							"company": self.company,
							"voucher_type": self.doctype,
							"voucher_no": self.name,
							"allow_zero_valuation": d.get("allow_zero_valuation"),
						},
						raise_error_if_no_rate=False,
					)

					rate = flt(outgoing_rate * (d.conversion_factor or 1), d.precision("rate"))
				else:
					# field = "incoming_rate" if self.get("is_internal_supplier") else "rate"
					field = "rate"
					rate = flt(
						frappe.db.get_value(ref_doctype, d.get(frappe.scrub(ref_doctype)), field)
						* (d.conversion_factor or 1),
						d.precision("rate"),
					)

				if self.is_internal_transfer():
					if rate != d.rate:
						d.rate = rate
						frappe.msgprint(
							_(
								"Row {0}: Item rate has been updated as per valuation rate since its an internal stock transfer"
							).format(d.idx),
							alert=1,
						)
					d.discount_percentage = 0.0
					d.discount_amount = 0.0
					d.margin_rate_or_amount = 0.0



@frappe.whitelist()
def make_purchase_order(source_name, target_doc=None):
	def set_missing_values(source, target):
		target.run_method("set_missing_values")
		target.run_method("get_schedule_dates")
		target.run_method("calculate_taxes_and_totals")

	def update_item(obj, target, source_parent):
		target.stock_qty = flt(obj.qty) * flt(obj.conversion_factor)

	doclist = get_mapped_doc(
		"Sales Order",
		source_name,
		{
			"Sales Order": {
				"doctype": "Purchase Order",
				"validation": {
					"docstatus": ["=", 1],
				},
			},
			"Sales Order Item": {
				"doctype": "Purchase Order Item",
				# "field_map": [
				# 	["name", "sales_order_item"],
				# 	["parent", "sales_order"],
				# ],
				# "postprocess": update_item,
			},
			"Purchase Taxes and Charges": {
				"doctype": "Purchase Taxes and Charges",
			},
		},
		target_doc,
		set_missing_values,
	)
	print("..........................................\ndoclist",doclist)
	doclist.set_onload("ignore_price_list", True)
	
	return doclist