import frappe
from frappe import _
import json
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt, getdate, nowdate, cint, cstr
from erpnext.controllers.buying_controller import BuyingController
from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder
from erpnext.buying.utils import validate_for_items
from frappe.utils import get_fullname, parse_addr
from frappe.desk.doctype.notification_log.notification_log import (
	enqueue_create_notification,
	get_title,
	get_title_html,
)
from frappe.desk.doctype.notification_settings.notification_settings import (
	get_subscribed_documents,
)
from frappe.core.doctype.communication.email import make


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
		if frappe.db.exists("Sales Order",{"name": sales_order_name}):
			frappe.db.set_value('Purchase Order Item', item_name, {
				'sales_order': sales_order_name,
				'avientek_eta':eta
				}, update_modified=False)

		so_child_eta_history = ''
		so_eta_history = eta_history_text = eta_history = []

		if frappe.db.exists("Sales Order Item",{"name": sales_order_item}):
			frappe.db.set_value('Purchase Order Item', item_name, {
				'sales_order_item':sales_order_item
				}, update_modified=False)
			so_child_eta_history = frappe.db.get_value("Sales Order Item", sales_order_item, ["eta_history"])

		
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
		return True

@frappe.whitelist()
def create_notification(ref_doctype,ref_name,item):
	try:
		doc = frappe.get_doc(ref_doctype,ref_name)
		title = get_title(ref_doctype, ref_name)
		filters = {
			"status": "Open",
			"reference_name": ref_name,
			"reference_type": ref_doctype,
		}

		rows = frappe.get_all("ToDo", filters=filters or {}, fields=["allocated_to"])
		rec =  [parse_addr(row.allocated_to)[1] for row in rows if row.allocated_to]
		rec.append(doc.owner)

		if ref_doctype == "Sales Order":
			if doc.po_no:
				if frappe.db.exists('Purchase Order',doc.po_no):
					cust_po = frappe.get_doc("Purchase Order",doc.po_no)
					rec.append(cust_po.owner)

		if item == '0':
			item = 'item(s)'

		notification_message = _("""ETA got updated for {0} in {1} {2}""").format(frappe.bold(item),frappe.bold(ref_name),get_title_html(title))
		notification_doc = {
			"type": "Alert",
			"document_type": ref_doctype,
			"document_name": ref_name,
			"subject": notification_message,
			"from_user": frappe.session.user,
		}

		enqueue_create_notification(rec, notification_doc)

		outgoing_email_account = frappe.get_cached_value(
				"Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "email_id"
			)

		for user in rec:
			if user != "Administrator":
				make(
						content = notification_message,
						subject = "ETA Updated",
						sender = outgoing_email_account,
						recipients = user,
						communication_medium = "Email",
						sent_or_received = "Sent",
						send_email = 1
					)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), str(e))

# from erpnext.controllers.item_variant import create_variant

# def execute():

# 	v = create_variant('XXXXXX', {'Colour':'Green'})
# 	# print(v)
# 	# v.item_code = 'XXXXXX-red'
# 	# print(v.item_code)
# 	v.save()

from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_received_items
from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_inter_company_details
from erpnext.accounts.doctype.sales_invoice.sales_invoice import set_purchase_references
from erpnext.accounts.doctype.sales_invoice.sales_invoice import update_address
from erpnext.accounts.doctype.sales_invoice.sales_invoice import update_taxes
from frappe.model.mapper import get_mapped_doc

@frappe.whitelist()
def make_inter_company_sales_order(source_name, target_doc=None):
	# from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_inter_company_transaction

	return make_inter_company_transaction("Purchase Order", source_name, target_doc)

@frappe.whitelist()
def make_inter_company_purchase_order(source_name, target_doc=None):
	# from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_inter_company_transaction

	return make_inter_company_transaction("Sales Order", source_name, target_doc)


def make_inter_company_transaction(doctype, source_name, target_doc=None):
	if doctype in ["Sales Invoice", "Sales Order"]:
		source_doc = frappe.get_doc(doctype, source_name)
		target_doctype = "Purchase Invoice" if doctype == "Sales Invoice" else "Purchase Order"
		target_detail_field = "sales_invoice_item" if doctype == "Sales Invoice" else "sales_order_item"
		source_document_warehouse_field = "target_warehouse"
		target_document_warehouse_field = "from_warehouse"
		received_items = get_received_items(source_name, target_doctype, target_detail_field)
	else:
		source_doc = frappe.get_doc(doctype, source_name)
		target_doctype = "Sales Invoice" if doctype == "Purchase Invoice" else "Sales Order"
		source_document_warehouse_field = "from_warehouse"
		target_document_warehouse_field = "target_warehouse"
		received_items = {}

	validate_inter_company_transaction(source_doc, doctype)
	details = get_inter_company_details(source_doc, doctype)

	def set_missing_values(source, target):
		target.run_method("set_missing_values")
		set_purchase_references(target)

	def update_details(source_doc, target_doc, source_parent):
		target_doc.inter_company_invoice_reference = source_doc.name
		if target_doc.doctype in ["Purchase Invoice", "Purchase Order"]:
			currency = frappe.db.get_value("Supplier", details.get("party"), "default_currency")
			target_doc.company = details.get("company")
			target_doc.supplier = details.get("party")
			target_doc.is_internal_supplier = 1
			target_doc.ignore_pricing_rule = 1
			target_doc.buying_price_list = source_doc.selling_price_list

			# Invert Addresses
			update_address(target_doc, "supplier_address", "address_display", source_doc.company_address)
			update_address(
				target_doc, "shipping_address", "shipping_address_display", source_doc.customer_address
			)
			update_address(
				target_doc, "billing_address", "billing_address_display", source_doc.customer_address
			)

			if currency:
				target_doc.currency = currency

			update_taxes(
				target_doc,
				party=target_doc.supplier,
				party_type="Supplier",
				company=target_doc.company,
				doctype=target_doc.doctype,
				party_address=target_doc.supplier_address,
				company_address=target_doc.shipping_address,
			)

		else:
			currency = frappe.db.get_value("Customer", details.get("party"), "default_currency")
			target_doc.company = details.get("company")
			target_doc.customer = details.get("party")
			target_doc.selling_price_list = source_doc.buying_price_list

			update_address(
				target_doc, "company_address", "company_address_display", source_doc.supplier_address
			)
			update_address(
				target_doc, "shipping_address_name", "shipping_address", source_doc.shipping_address
			)
			update_address(target_doc, "customer_address", "address_display", source_doc.shipping_address)

			if currency:
				target_doc.currency = currency

			update_taxes(
				target_doc,
				party=target_doc.customer,
				party_type="Customer",
				company=target_doc.company,
				doctype=target_doc.doctype,
				party_address=target_doc.customer_address,
				company_address=target_doc.company_address,
				shipping_address_name=target_doc.shipping_address_name,
			)

	def update_item(source, target, source_parent):
		target.qty = flt(source.qty) - received_items.get(source.name, 0.0)
		if source.doctype == "Purchase Order Item" and target.doctype == "Sales Order Item":
			target.purchase_order = source.parent
			target.purchase_order_item = source.name
			target.material_request = source.material_request
			target.material_request_item = source.material_request_item

		if (
			source.get("purchase_order")
			and source.get("purchase_order_item")
			and target.doctype == "Purchase Invoice Item"
		):
			target.purchase_order = source.purchase_order
			target.po_detail = source.purchase_order_item

	item_field_map = {
		"doctype": target_doctype + " Item",
		"field_no_map": ["income_account", "expense_account", "cost_center", "warehouse"],
		"field_map": {
			"rate": "rate",
		},
		"postprocess": update_item,
		"condition": lambda doc: doc.qty > 0,
	}

	if doctype in ["Sales Invoice", "Sales Order"]:
		item_field_map["field_map"].update(
			{
				"name": target_detail_field,
			}
		)

	if source_doc.get("update_stock"):
		item_field_map["field_map"].update(
			{
				source_document_warehouse_field: target_document_warehouse_field,
				"batch_no": "batch_no",
				"serial_no": "serial_no",
			}
		)
	elif target_doctype == "Sales Order":
		item_field_map["field_map"].update(
			{
				source_document_warehouse_field: "warehouse",
			}
		)

	doclist = get_mapped_doc(
		doctype,
		source_name,
		{
			doctype: {
				"doctype": target_doctype,
				"postprocess": update_details,
				"set_target_warehouse": "set_from_warehouse",
				"field_no_map": ["taxes_and_charges", "set_warehouse", "shipping_address"],
			},
			doctype + " Item": item_field_map,
		},
		target_doc,
		set_missing_values,
	)

	return doclist


def validate_inter_company_transaction(doc, doctype):

	details = get_inter_company_details(doc, doctype)
	price_list = (
		doc.selling_price_list
		if doctype in ["Sales Invoice", "Sales Order", "Delivery Note"]
		else doc.buying_price_list
	)
	valid_price_list = frappe.db.get_value(
		"Price List", {"name": price_list, "buying": 1, "selling": 1}
	)
	if not valid_price_list and not doc.is_internal_transfer():
		frappe.throw(_("Selected Price List should have buying and selling fields checked."))

	party = details.get("party")
	if not party:
		partytype = "Supplier" if doctype in ["Sales Invoice", "Sales Order"] else "Customer"
		frappe.throw(_("No {0} found for Inter Company Transactions.").format(partytype))

	# company = details.get("company")
	# default_currency = frappe.get_cached_value("Company", company, "default_currency")
	# if default_currency != doc.currency:
	# 	frappe.throw(
	# 		_("Company currencies of both the companies should match for Inter Company Transactions.")
	# 	)

	return