"""#0599: fill the read-only Special Price / Note on existing Purchase Order
lines that have none, where the Quotation behind them has one.

Two cases were never filled (see purchase_order._special_price_sources):
inter-company orders (the price was lost between the two companies) and
orders whose Sales Order was made before Special Price was carried to Sales
Orders. Display-only columns: no rate, amount, total or GL is touched, and the
PO's modified date is left alone. Lines that already show a price are skipped.
Idempotent.
"""
import frappe
from frappe.utils import flt


def execute():
	from avientek.events.purchase_order import _convert_txn_amount, _special_price_sources

	if not frappe.db.has_column("Purchase Order Item", "custom_special_price"):
		return

	rows = frappe.db.sql(
		"""SELECT pi.name, pi.sales_order_item, po.currency, po.conversion_rate
		   FROM `tabPurchase Order Item` pi
		   JOIN `tabPurchase Order` po ON po.name = pi.parent
		   WHERE po.docstatus < 2 AND IFNULL(pi.sales_order_item, '') != ''
		     AND IFNULL(pi.custom_special_price, 0) = 0""",
		as_dict=True,
	)
	done = 0
	for i in range(0, len(rows), 500):
		chunk = rows[i:i + 500]
		sources = _special_price_sources([r.sales_order_item for r in chunk])
		for r in chunk:
			src = sources.get(r.sales_order_item)
			if not src or not flt(src.value):
				continue
			frappe.db.set_value("Purchase Order Item", r.name, {
				"custom_special_price": _convert_txn_amount(
					src.value, src.currency, src.rate, r.currency, r.conversion_rate),
				"custom_special_price_note": src.note,
			}, update_modified=False)
			done += 1
		frappe.db.commit()
	if done:
		print(f"[#0599] Special Price filled on {done} Purchase Order lines")
