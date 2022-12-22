import frappe
from frappe import _
import json
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


def po_validate(doc, method):
	doc_before_save = doc.get_doc_before_save()
	if doc.items:
		for i, item in enumerate(doc.items):
			if item.avientek_eta and doc_before_save.items[i] \
				and item.avientek_eta != doc_before_save.items[i].avientek_eta and item.name == doc_before_save.items[i].name:
				if item.sales_order and item.sales_order_item:
					so_eta_history = []
					so_child_doc = frappe.db.get_value("Sales Order Item", item.sales_order_item, ["eta_history", "purchase_order_item"], as_dict=1)
					if so_child_doc.eta_history:
						so_eta_history = append_to_eta_list(item.avientek_eta, so_child_doc.eta_history)
					else:
						so_eta_history = [{"eta": item.avientek_eta, "date": frappe.utils.nowdate()}]
					so_eta_history_text = set_history(so_eta_history)
					frappe.db.set_value("Sales Order Item", item.sales_order_item, {
						"avientek_eta": item.avientek_eta,
						"eta_history": json.dumps(so_eta_history),
						"eta_history_text": so_eta_history_text
						}, update_modified = False)
					if so_child_doc.purchase_order_item:
						first_po_eta_history = frappe.db.get_value("Purchase Order Item", so_child_doc.purchase_order_item, ["eta_history"])
						f_po_eta_history = []
						if first_po_eta_history:
							f_so_eta_history = append_to_eta_list(item.avientek_eta, first_po_eta_history)
						else:
							f_so_eta_history = [{"eta": item.avientek_eta, "date": frappe.utils.nowdate()}]
						f_po_eta_history = f_so_eta_history
						po_eta_history_text = set_history(f_so_eta_history)
						frappe.db.set_value("Purchase Order Item", so_child_doc.purchase_order_item, {
							"avientek_eta": item.avientek_eta,
							"eta_history": json.dumps(f_po_eta_history),
							"eta_history_text": po_eta_history_text
							}, update_modified = False)
				# set in same doc
				po_eta_history = []
				if item.eta_history:
					po_eta_history = append_to_eta_list(item.avientek_eta, item.eta_history)
				else:
					po_eta_history = [{"eta": item.avientek_eta, "date": frappe.utils.nowdate()}]
				item.eta_history = json.dumps(po_eta_history)
				item.eta_history_text = set_history(po_eta_history)


def append_to_eta_list(avientek_eta, eta_history):
	eta_history = json.loads(eta_history)
	if eta_history:
		eta_history += [{'eta': avientek_eta, 'date': frappe.utils.nowdate()}]
	return eta_history


def set_history(po_eta_history):
	item_details_html = '''<table border="1px grey"  bordercolor="grey" style="width: 100%; height:100">
	<tr style="height: 15px;">
	<td style="text-align: center; color:#687178; width:10%">No.</td>
	<td style="text-align: center; color:#687178; width:40%">Date</td>
	<td style="text-align: center; color:#687178; width:55%">ETA</td>
	</tr>'''
	for i, eta in enumerate(po_eta_history):
		item_details_html += "<tbody><tr>"
		item_details_html += '<td style="text-align: center; background-color:#FFFF; font-size: 12px;">' + str(i+1) + '</td>'
		item_details_html += '<td style="text-align: center; background-color:#FFFF; font-size: 12px;">' + eta.get('date') + '</td>'
		item_details_html += '<td style="text-align: center; background-color:#FFFF; font-size: 12px;">' + eta.get('eta') + '</td>'
		item_details_html += "</tr></tbody>"
	return item_details_html


@frappe.whitelist()
def get_sales_orders(item, qty, sales_order):
	so_option = []
	query = f"""
		SELECT
			soi.name AS child,
			so.name AS so,
			so.customer AS customer,
			soi.qty AS qty
		FROM
			`tabSales Order Item` as soi LEFT JOIN
			`tabSales Order` as so ON soi.parent = so.name
		WHERE
			soi.item_code = {frappe.db.escape(item)} AND
			soi.qty <= {qty} AND
			so.name != {frappe.db.escape(sales_order)} AND
			so.is_internal_customer=0 AND
			so.status = {frappe.db.escape("To Deliver and Bill")}
			"""
	sales_orders = frappe.db.sql(query, as_dict=1)
	for so in sales_orders:
		if so.get('so'):
			so_option.append({
				"label": str(so.get('so'))+" - "+str(so.get('customer'))+" - "+str(so.get('qty')),
				"value": str(so.get('so'))+" | "+str(so.get('child'))
			})
	return so_option


@frappe.whitelist()
def set_sales_order(sales_order, item_name, eta):
	if sales_order and sales_order.split("| ")[1]:
		sales_order_name = sales_order.split("| ")[0].strip()
		sales_order_item = sales_order.split("| ")[1]
		frappe.db.set_value('Purchase Order Item', item_name, {
			'sales_order': sales_order_name,
			'sales_order_item':sales_order_item
			}, update_modified=False)
		so_child_eta_history = frappe.db.get_value("Sales Order Item", sales_order_item, ["eta_history"])
		so_eta_history = eta_history_text = eta_history = []
		if so_child_eta_history:
			so_eta_history = append_to_eta_list(eta, so_child_eta_history)
		else:
			so_eta_history = [{"eta": eta, "date": frappe.utils.nowdate()}]
		eta_history_text = set_history(so_eta_history)
		eta_history = json.dumps(so_eta_history)
		frappe.db.set_value("Sales Order Item", sales_order_item, {
			"avientek_eta": eta,
			"eta_history_text": eta_history_text,
			"eta_history" : eta_history
			})
