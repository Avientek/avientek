import frappe
from frappe import _
import json
from frappe.model.mapper import get_mapped_doc
from frappe.utils.pdf import get_pdf
from frappe.utils.file_manager import save_file
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
from erpnext.setup.utils import get_exchange_rate


# ── Server Script: "PO Validate supplier company" ──
# DocType Event: Purchase Order, Before Validate
# NOTE: Already partially handled in check_exchange_rate -> po_validate,
#       but the supplier company check is done separately in the server script.
def validate_supplier_company(doc, method=None):
    """Ensure supplier belongs to the same company on the PO."""
    if doc.supplier and doc.company and not doc.is_internal_supplier:
        supplier = frappe.get_doc("Supplier", doc.supplier)
        if supplier.company and supplier.company != doc.company:
            frappe.throw(_("Supplier does not belongs to company"))


# ── Server Script: "PO - Item Tax Template" ──
# DocType Event: Purchase Order, Before Validate
def validate_item_tax_template(doc, method=None):
    """Auto-fill Item Tax Template from Item master, then hard-require
    it for Avientek Electronics Trading PVT. LTD."""
    from avientek.events.utils import autofill_item_tax_template
    required = "Avientek Electronics Trading PVT. LTD" if doc.company == "Avientek Electronics Trading PVT. LTD" else None
    autofill_item_tax_template(doc, required_company=required)


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

def autofill_foreign_conversion_rate(doc, method=None):
	"""before_validate: guarantee a foreign-currency Purchase Order carries
	the real transaction-currency -> company-currency exchange rate, so its
	base (company-currency) amounts are actually converted.

	Sammish 2026-08-05 (AVFZC-02535 / PO-FZCO-26-00955): a EUR PO was saved
	with conversion_rate = 1.0, so every base/AED amount equalled the EUR
	amount (EUR 7,742.70 shown as AED 7,742.70 instead of ~AED 30,900), and
	the PRF Payment Voucher inherited the wrong figure. The existing
	check_exchange_rate() below only runs when currency == price_list_currency;
	this PO was EUR transaction / USD price list, so that guard was skipped
	entirely and the 1.0 rate slipped through.

	Fix: whenever the transaction currency differs from the company's
	default currency but conversion_rate is missing or 1.0 (the tell-tale of
	an unconverted foreign document — no currency the company deals in is
	pegged 1:1 to AED), pull the real rate from Currency Exchange and set it
	here, in before_validate, so the controller's calculate_taxes_and_totals
	then recomputes every base amount correctly. If no system rate exists,
	block the save with a clear message rather than persist a wrong 1.0.

	A genuine, non-1.0 rate the user/ERPNext already set is left untouched.
	"""
	if not doc.currency:
		return
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency")
	if not company_currency or doc.currency == company_currency:
		return  # base-currency PO — conversion_rate 1.0 is correct

	rate = flt(doc.conversion_rate)
	if rate and abs(rate - 1.0) > 1e-9:
		return  # a real (non-1.0) foreign rate is already set — respect it

	txn_date = doc.transaction_date or nowdate()
	sys_rate = flt(get_exchange_rate(doc.currency, company_currency, txn_date))
	if sys_rate and abs(sys_rate - 1.0) > 1e-9:
		doc.conversion_rate = sys_rate
		frappe.msgprint(
			_("Exchange rate for {0} → {1} was set to {2} from Currency Exchange "
			  "(it was left at 1.0). Base amounts recalculated.").format(
				doc.currency, company_currency, sys_rate),
			indicator="blue", alert=True,
		)
	else:
		frappe.throw(
			_("Purchase Order is in {0} but has no valid exchange rate to the "
			  "company currency {1} for {2}. Set the correct conversion rate "
			  "(or add a Currency Exchange record) before saving — a rate of 1.0 "
			  "would book base amounts equal to the {0} amounts.").format(
				doc.currency, company_currency, txn_date)
		)


def check_exchange_rate(doc,method):
	po_validate(doc,method)
	if doc.currency == doc.price_list_currency:
		if doc.conversion_rate and doc.plc_conversion_rate:
		    if doc.conversion_rate != doc.plc_conversion_rate:
		        frappe.throw("Exchange rate and price list exchange rate should be the same!")
		    else:
		    	company_default_currency = frappe.get_cached_value("Company", doc.company, "default_currency")
		    	exc_rate = get_exchange_rate(doc.currency, company_default_currency, doc.transaction_date)
		    	if (exc_rate != doc.conversion_rate) or (exc_rate != doc.plc_conversion_rate):
		    		frappe.throw("Exchange rate is wrong!")

def _convert_txn_amount(value, from_currency, from_rate, to_currency, to_rate):
	"""Convert a transaction-currency amount from one document's currency into
	another document's currency, via the company (base) currency.

	Sridhar 2026-08-31: an ERPNext document stores only `conversion_rate` —
	its OWN transaction currency -> company currency. There is no direct
	SO-currency -> PO-currency rate anywhere, so the amount has to go through
	base:

		base   = value * from_rate      # SO currency -> AED
		result = base  / to_rate        # AED -> PO currency

	Same-currency rows are returned untouched rather than round-tripped, so a
	PO raised on a different date than its Sales Order (and therefore holding
	a slightly different rate for the same currency) can never drift an amount
	that needed no conversion in the first place.
	"""
	value = flt(value)
	if not value:
		return value
	if from_currency and to_currency and from_currency == to_currency:
		return value
	from_rate = flt(from_rate) or 1.0
	to_rate = flt(to_rate) or 1.0
	if to_rate <= 0:
		return value
	return flt(value * from_rate / to_rate, 4)


def sync_special_price_from_sales_order(doc, method=None):
	"""Refresh read-only Special Price / Special Price Note on each PO Item
	that's linked to a Sales Order Item (via sales_order_item).

	Orders.Mea 2026-08-17: client wants Quotation's Special Price /
	Special Price Note visible on the connected SO and PO. On the SO side
	these are copied from the Quotation (see
	avientek.events.sales_order.carry_forward_quotation_fields). On the PO
	side there's no single mapper path — rows get linked to an SO Item via
	the standard "Get Items From" mapper, the "Swap Sales Order" dialog, or
	direct entry — so this hook re-fetches from whichever SO Item is
	currently linked, on every save. Rows with no sales_order_item are left
	untouched (not every PO is tied to a Sales Order).

	Sridhar 2026-08-31: Special Price is denominated in the currency of the
	document it lives on, so a straight copy relabelled an SO-currency figure
	with the PO's symbol (SO 555.55 AED shown as "USD 555.55"). Convert into
	THIS PO's currency using the two documents' own conversion rates — see
	_convert_txn_amount(). This runs after autofill_foreign_conversion_rate in
	the before_validate list (see hooks.py), so doc.conversion_rate is already
	the corrected rate by the time we divide by it.

	Draft only. Sridhar 2026-09-02 (POLTD26-27-00205): this also ran at
	before_update_after_submit, where writing a field that isn't
	allow_on_submit makes Frappe's validate_update_after_submit abort the
	ENTIRE save -- not just this column. Rahul's PO held 143904.0 (the
	company-currency figure, = 1483.5464 x its conversion_rate of 97) while
	its Sales Order Item held 1483.5464, so the rewrite was never a no-op
	and every save died with "Row #1: Not allowed to change Special Price
	after submission", leaving the PO unable to be edited, ticked for
	revision, or moved through the workflow at all.

	These two columns are a read-only informational mirror -- they exist so
	a buyer can see what price was quoted, nothing reads them back. So the
	fix is to stop writing them after submit, NOT to make them
	allow_on_submit: the value is meant to stay frozen at whatever the PO
	was submitted with. That does mean a row skewed by the pre-conversion
	bug this branch fixes does NOT self-heal on its next save once the PO is
	submitted -- correcting an already-submitted row now takes a deliberate
	frappe.db.set_value. Draft rows still self-heal normally.

	The one post-submit path that legitimately re-points a row at a
	different SO Item (the "Swap Sales Order" dialog) refreshes the mirror
	through update_eta's frappe.db.set_value, which bypasses the submit
	check by design and is left working.
	"""
	if doc.docstatus != 0:
		return

	if not doc.items:
		return

	so_items = [it.sales_order_item for it in doc.items if getattr(it, "sales_order_item", None)]
	if not so_items:
		return

	so_rows = frappe.db.get_all(
		"Sales Order Item",
		filters={"name": ["in", so_items]},
		fields=["name", "parent", "custom_special_price", "custom_special_price_note"],
	)
	so_map = {so.name: so for so in so_rows}

	# Currency + rate of each source Sales Order. A PO can pull rows from
	# several SOs, so resolve them per parent rather than assuming one.
	so_parents = {so.parent for so in so_rows if so.parent}
	so_doc_map = {}
	if so_parents:
		so_doc_map = {
			so.name: so for so in frappe.db.get_all(
				"Sales Order",
				filters={"name": ["in", list(so_parents)]},
				fields=["name", "currency", "conversion_rate"],
			)
		}

	for item in doc.items:
		so_item = so_map.get(getattr(item, "sales_order_item", None))
		if not so_item:
			continue
		so_doc = so_doc_map.get(so_item.parent) or frappe._dict()
		item.custom_special_price = _convert_txn_amount(
			so_item.custom_special_price,
			so_doc.currency, so_doc.conversion_rate,
			doc.currency, doc.conversion_rate,
		)
		item.custom_special_price_note = so_item.custom_special_price_note


@frappe.whitelist()
def get_special_prices_for_currency(sales_order_items, currency=None, conversion_rate=None):
	"""Return {sales_order_item: Special Price expressed in `currency`}.

	Sridhar 2026-08-31: the PO form only repainted the Special Price column on
	save — pick a supplier and the currency symbol and conversion rate flipped
	instantly while the figure underneath stayed in the Sales Order's currency
	until the save round-tripped. purchase_order.js calls this the moment the
	rate settles so the column tracks the header.

	Display-only: sync_special_price_from_sales_order() recomputes the same
	values server-side on every save, so a stale, failed or skipped client call
	can never persist a wrong number — it only delays the repaint.

	Deliberately unguarded by a Sales Order permission check, matching
	line_update_eta() above: the whole point of these columns is to show buyers
	what was quoted WITHOUT giving them access to the Quotation or Sales Order.
	"""
	if isinstance(sales_order_items, str):
		sales_order_items = json.loads(sales_order_items)
	sales_order_items = [n for n in (sales_order_items or []) if n]
	if not sales_order_items:
		return {}

	so_rows = frappe.db.get_all(
		"Sales Order Item",
		filters={"name": ["in", sales_order_items]},
		fields=["name", "parent", "custom_special_price"],
	)

	so_parents = {so.parent for so in so_rows if so.parent}
	so_doc_map = {}
	if so_parents:
		so_doc_map = {
			so.name: so for so in frappe.db.get_all(
				"Sales Order",
				filters={"name": ["in", list(so_parents)]},
				fields=["name", "currency", "conversion_rate"],
			)
		}

	out = {}
	for so in so_rows:
		so_doc = so_doc_map.get(so.parent) or frappe._dict()
		out[so.name] = _convert_txn_amount(
			so.custom_special_price,
			so_doc.currency, so_doc.conversion_rate,
			currency, conversion_rate,
		)
	return out


# def po_validate(doc, method):
	# doc_before_save = doc.get_doc_before_save()
	# if doc.items:
	# 	for i, item in enumerate(doc.items):
	# 		if item.avientek_eta and doc_before_save.items[i] \
	# 			and item.avientek_eta != doc_before_save.items[i].avientek_eta and item.name == doc_before_save.items[i].name:
	# 			if item.sales_order and item.sales_order_item:
	# 				so_eta_history = []
	# 				so_child_doc = frappe.db.get_value("Sales Order Item", item.sales_order_item, ["eta_history", "purchase_order_item"], as_dict=1)
	# 				if so_child_doc.eta_history:
	# 					so_eta_history = append_to_eta_list(item.avientek_eta, so_child_doc.eta_history)
	# 				else:
	# 					so_eta_history = [{"eta": item.avientek_eta, "date": frappe.utils.nowdate()}]
	# 				so_eta_history_text = set_history(so_eta_history)
	# 				frappe.db.set_value("Sales Order Item", item.sales_order_item, {
	# 					"avientek_eta": item.avientek_eta,
	# 					"eta_history": json.dumps(so_eta_history),
	# 					"eta_history_text": so_eta_history_text
	# 					}, update_modified = False)
	# 				if so_child_doc.purchase_order_item:
	# 					first_po_eta_history = frappe.db.get_value("Purchase Order Item", so_child_doc.purchase_order_item, ["eta_history"])
	# 					f_po_eta_history = []
	# 					if first_po_eta_history:
	# 						f_so_eta_history = append_to_eta_list(item.avientek_eta, first_po_eta_history)
	# 					else:
	# 						f_so_eta_history = [{"eta": item.avientek_eta, "date": frappe.utils.nowdate()}]
	# 					f_po_eta_history = f_so_eta_history
	# 					po_eta_history_text = set_history(f_so_eta_history)
	# 					frappe.db.set_value("Purchase Order Item", so_child_doc.purchase_order_item, {
	# 						"avientek_eta": item.avientek_eta,
	# 						"eta_history": json.dumps(f_po_eta_history),
	# 						"eta_history_text": po_eta_history_text
	# 						}, update_modified = False)
	# 			# set in same doc
	# 			po_eta_history = []
	# 			if item.eta_history:
	# 				po_eta_history = append_to_eta_list(item.avientek_eta, item.eta_history)
	# 			else:
	# 				po_eta_history = [{"eta": item.avientek_eta, "date": frappe.utils.nowdate()}]
	# 			item.eta_history = json.dumps(po_eta_history)
	# 			item.eta_history_text = set_history(po_eta_history)

# item is purchase order item
@frappe.whitelist()
def line_update_eta(item):
	item = json.loads(item)
	item = frappe._dict(item)
	if item:
		update_eta(item)

def update_eta(item):
	eta = item.avientek_eta
	# Proceed if Sales Order and Sales Order Item are present
	if item.sales_order and item.sales_order_item:
		so_child_doc = frappe.db.get_value(
			"Sales Order Item",
			item.sales_order_item,
			["eta_history", "purchase_order_item", "custom_special_price", "custom_special_price_note"],
			as_dict=True
		)

		so_eta_history = append_to_eta_list(item.avientek_eta, so_child_doc.eta_history) if so_child_doc.eta_history else [{"eta": item.avientek_eta, "date": frappe.utils.nowdate()}]
		so_eta_history_text = set_history(so_eta_history)

		frappe.db.set_value("Sales Order Item", item.sales_order_item, {
			"avientek_eta": item.avientek_eta,
			"eta_history": json.dumps(so_eta_history),
			"eta_history_text": so_eta_history_text
		}, update_modified=False)

		# Orders.Mea 2026-08-17: this PO row is now (re)linked to this SO
		# row via the "Swap Sales Order" dialog — refresh the read-only
		# Special Price / Special Price Note columns from the SO Item.
		# Sridhar 2026-08-31: convert into this PO's currency, same as
		# sync_special_price_from_sales_order above. This path writes
		# straight to the DB (no doc in hand), so both parents are read
		# here. `item` arrives either as a child doc (po_validate) or as a
		# _dict parsed from the JS dialog payload (line_update_eta) — both
		# answer .get("parent"), with a DB read as the fallback.
		po_parent = item.get("parent") or frappe.db.get_value(
			"Purchase Order Item", item.name, "parent"
		)
		so_doc = frappe.db.get_value(
			"Sales Order", item.sales_order, ["currency", "conversion_rate"], as_dict=True
		) or frappe._dict()
		po_doc = frappe.db.get_value(
			"Purchase Order", po_parent, ["currency", "conversion_rate"], as_dict=True
		) if po_parent else None
		po_doc = po_doc or frappe._dict()
		frappe.db.set_value("Purchase Order Item", item.name, {
			"custom_special_price": _convert_txn_amount(
				so_child_doc.custom_special_price,
				so_doc.currency, so_doc.conversion_rate,
				po_doc.currency, po_doc.conversion_rate,
			),
			"custom_special_price_note": so_child_doc.custom_special_price_note,
		}, update_modified=False)

		# Handle Purchase Order Item ETA history if linked to Sales Order
		if so_child_doc.purchase_order_item:
			# Fetch the Purchase Order Item's existing ETA history
			first_po_eta_history = frappe.db.get_value("Purchase Order Item", so_child_doc.purchase_order_item, "eta_history")
			po_eta_history = append_to_eta_list(item.avientek_eta, first_po_eta_history) if first_po_eta_history else [{"eta": item.avientek_eta, "date": frappe.utils.nowdate()}]
			po_eta_history_text = set_history(po_eta_history)

			frappe.db.set_value("Purchase Order Item", so_child_doc.purchase_order_item, {
				"avientek_eta": item.avientek_eta,
				"eta_history": json.dumps(po_eta_history),
				"eta_history_text": po_eta_history_text
			}, update_modified=False)

	# Update ETA history in the current Purchase Order line item
	po_eta_history = append_to_eta_list(item.avientek_eta, item.eta_history) if item.eta_history else [{"eta": item.avientek_eta, "date": frappe.utils.nowdate()}]
	frappe.db.set_value("Purchase Order Item",item.name,"avientek_eta",eta)
	frappe.db.set_value("Purchase Order Item",item.name,"eta_history",json.dumps(po_eta_history))
	frappe.db.set_value("Purchase Order Item",item.name,"eta_history_text",set_history(po_eta_history))

def po_validate(doc, method):
	"""Detect ETA changes per row and fire update_eta on changed rows.

	Sammish 2026-06-26 (Rahul POLTD26-27-00128 PROD URGENT): the previous
	implementation iterated `doc.items` by index and accessed
	`doc_before_save.items[i]` directly. When a new line was added to the
	PO (Rahul's case — second SO line from SO-LTD-26-27-00332), the
	current `doc.items` length exceeded `doc_before_save.items` and the
	loop blew up with `IndexError: list index out of range` on save.

	Fix: index `doc_before_save.items` by row `name` and skip rows that
	don't exist in the prior snapshot (newly added — no ETA history to
	compare against). Also skip when the prior row has no eta to detect
	a "change" against.
	"""
	doc_before_save = doc.get_doc_before_save()
	if not doc_before_save:
		return
	if not doc.items:
		return

	before_by_name = {row.name: row for row in (doc_before_save.items or []) if row.name}

	for item in doc.items:
		if not item.avientek_eta:
			continue
		before_item = before_by_name.get(item.name)
		if not before_item:
			# Newly inserted row — no prior eta to compare to. Treat as
			# a first-time set, which update_eta handles via its
			# append-or-seed branch.
			update_eta(item)
			continue
		if item.avientek_eta != before_item.avientek_eta:
			update_eta(item)


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
	print("\n..........................")
	print("\nsales order item eta",sales_order,item_name, eta)
	if sales_order and sales_order.split("| ")[1]:
		sales_order_name = sales_order.split("| ")[0].strip()
		sales_order_item = sales_order.split("| ")[1]
		print("\n...sales order",sales_order_name,sales_order_item)
		if frappe.db.exists("Sales Order",{"name": sales_order_name}):
			print("sales order exists... lets update the po eta",item_name)
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
def create_notification(ref_doctype, ref_name=None, item=None):
	# Guard: the JS caller (send_notification in purchase_order.js) sometimes
	# fires with an undefined ref_name, raising "create_notification() missing
	# 1 required positional argument: 'ref_name'" (~52x/2d in prod). Make the
	# args optional and no-op when the reference is incomplete.
	if not ref_doctype or not ref_name:
		return
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

@frappe.whitelist()
def create_payment_request(source_name, target_doc=None, args=None):
    def set_single_reference(source, target):
        # Jithin 2026-05-12: PO -> PRF mapping wasn't setting party_type
        # or party — get_mapped_doc only copies fields with matching
        # names, and PO has `supplier` (not `party`). So the new PRF
        # came up with blank Party Type / Party. Fill them explicitly.
        target.party_type = "Supplier"
        target.party = source.supplier
        if hasattr(target, "party_name"):
            target.party_name = source.supplier_name or source.supplier
        # Pay against PO (not Advance Pay — Advance Pay has its own
        # "Get Open Purchase Orders" picker in PRF).
        if not target.payment_type:
            target.payment_type = "Pay"
        # Default currency / exchange_rate from PO if PRF doesn't already
        # carry them via field-name match.
        if not target.currency:
            target.currency = source.currency
        if not target.company:
            target.company = source.company

        # 3. Append to payment references
        # Jithin 2026-05-21: prior code put the first PO item's linked
        # Sales Order into `document_reference`, and the PO name into
        # `reference_name`. That violates the canonical contract for
        # this row (established 2026-05-18): `document_reference` must
        # point to a document of the type given by `reference_doctype`.
        # For PO rows the convention is:
        #   - reference_name = ""    (user fills the supplier invoice
        #                             number when goods arrive)
        #   - bill_no        = ""
        #   - document_reference = PO name (canonical system pointer)
        # Matches the existing _open_po_picker and _fetch_outstanding
        # PO flows. The Sales Order link is still reachable via PO's
        # "Connections" tab or PO Item's sales_order field — no need
        # to leak it into document_reference.
        exchange_rate = source.conversion_rate or 1
        # PO doesn't have outstanding_amount, use grand_total as full amount
        os_company = source.base_grand_total or 0
        os_invoice = source.grand_total or 0

        target.append("payment_references", {
            "reference_doctype": "Purchase Order",
            "reference_name": "",
            "bill_no": "",
            "grand_total": source.grand_total,
            "base_grand_total": source.base_grand_total,
            "outstanding_amount": os_invoice,
            "base_outstanding_amount": os_company,
            "invoice_date": source.transaction_date,
            "due_date": source.schedule_date,
            "exchange_rate": exchange_rate,
            "document_reference": source.name,
            "currency": source.currency,
        })

        # 4. Calculate totals
        target.total_outstanding_amount = sum((row.base_outstanding_amount or 0) for row in target.payment_references)
        target.total_payment_amount = sum((row.outstanding_amount or 0) for row in target.payment_references)
        target.total_amount = sum((row.grand_total or 0) for row in target.payment_references)

    # Create mapped Payment Request Form
    target_doc = get_mapped_doc(
        "Purchase Order",
        source_name,
        {
            "Purchase Order": {
                "doctype": "Payment Request Form",
            },
        },
        target_doc,
        postprocess=set_single_reference
    )

    return target_doc

@frappe.whitelist()
def get_items_from_internal_so(source_name, target_doc=None):
    from frappe.model.mapper import get_mapped_doc

    def update_item(source, target, source_parent):
        # Only copy desired fields
        target.item_code = source.item_code
        target.item_name = source.item_name
        target.description = source.description
        target.uom = source.uom
        target.qty = source.qty
        target.schedule_date = source.delivery_date
        target.rate = source.rate

    # ✅ MUST ACCEPT 3 PARAMETERS
    def update_parent(source, target, source_parent):
        # Prevent copying of terms & conditions
        target.tc_name = None
        target.terms = None

        # Also remove hidden auto-copied fields
        if hasattr(target, "terms_and_conditions"):
            target.terms_and_conditions = None

    doc = get_mapped_doc(
        "Sales Order",
        source_name,
        {
            "Sales Order": {
                "doctype": "Purchase Order",
                "postprocess": update_parent
            },
            "Sales Order Item": {
                "doctype": "Purchase Order Item",
                "postprocess": update_item
            }
        },
        target_doc
    )

    return doc

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

			# update_taxes(
			# 	target_doc,
			# 	party=target_doc.supplier,
			# 	party_type="Supplier",
			# 	company=target_doc.company,
			# 	doctype=target_doc.doctype,
			# 	party_address=target_doc.supplier_address,
			# 	company_address=target_doc.shipping_address,
			# )

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

			# update_taxes(
			# 	target_doc,
			# 	party=target_doc.customer,
			# 	party_type="Customer",
			# 	company=target_doc.company,
			# 	doctype=target_doc.doctype,
			# 	party_address=target_doc.customer_address,
			# 	company_address=target_doc.company_address,
			# 	shipping_address_name=target_doc.shipping_address_name,
			# )

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
