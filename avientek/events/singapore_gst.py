"""Singapore GST picked automatically on sales documents (#0601, Jithin).

Jithin 2026-11-18: "when the transactions are Local sales GST to be charged
automated, and when it is an export or zero rate transaction GST to be
calculated zero. Not required to amend any existing documents."

Rule, for a company whose country is Singapore:
  * goods delivered in Singapore  -> "Singapore Tax - <abbr>"      (GST 9%)
  * goods delivered anywhere else -> "Singapore GST 0% - <abbr>"   (GST 0%)
"Delivered" is the Shipping Address when there is one, otherwise the Billing
Address. The billing country alone is not enough: the invoices billed to a
Singapore company but shipped to India (INV-AVS-25-00001..4) are exports.

An ERPNext Tax Rule cannot express "shipping address, else billing address",
so this is a small hook instead.

When it acts (drafts only):
  * the document has no tax template and no tax rows  -> fill it;
  * the delivery address was changed and the document still carries one of
    the two automatic templates                        -> switch it.
A template the user picked by hand is otherwise left alone, so a local
zero-rated supply can still be set to 0%. With no address at all nothing is
filled. Credit notes copy the taxes of their invoice and are skipped.
"""
import frappe
from frappe import _

_DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice")
_COUNTRY = "Singapore"


def _templates(company):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	return f"Singapore Tax - {abbr}", f"Singapore GST 0% - {abbr}"


def _delivery_country(doc):
	for field in ("shipping_address_name", "customer_address"):
		address = doc.get(field)
		if address:
			country = frappe.db.get_value("Address", address, "country")
			if country:
				return country
	return None


def autofill_singapore_sales_taxes_template(doc, method=None, *args, **kwargs):
	if doc.doctype not in _DOCTYPES or doc.docstatus != 0 or not doc.get("company"):
		return
	if frappe.get_cached_value("Company", doc.company, "country") != _COUNTRY:
		return
	if doc.get("is_return"):
		return

	local_template, export_template = _templates(doc.company)
	country = _delivery_country(doc)
	if not country:
		return
	wanted = local_template if country == _COUNTRY else export_template
	if not frappe.db.exists("Sales Taxes and Charges Template", {"name": wanted, "disabled": 0}):
		return

	current = doc.get("taxes_and_charges")
	if current == wanted and doc.get("taxes"):
		return

	blank = not current and not doc.get("taxes")
	switch = False
	if not blank and current in (local_template, export_template):
		before = doc.get_doc_before_save()
		switch = bool(before) and any(
			(before.get(f) or "") != (doc.get(f) or "")
			for f in ("shipping_address_name", "customer_address")
		)
	refill = current == wanted and not doc.get("taxes")
	if not (blank or switch or refill):
		return

	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	doc.taxes_and_charges = wanted
	doc.set("taxes", [])
	for row in get_taxes_and_charges("Sales Taxes and Charges Template", wanted) or []:
		doc.append("taxes", row)

	if switch:
		frappe.msgprint(
			_("Delivery address is in {0}: tax template changed from {1} to {2}.").format(
				frappe.bold(country), frappe.bold(current), frappe.bold(wanted)),
			indicator="orange", alert=True,
		)
