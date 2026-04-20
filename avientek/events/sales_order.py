import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt


def carry_forward_quotation_fields(doc, method=None):
    """Restore payment terms and other fields from source Quotation.

    ERPNext's set_missing_values resets payment_terms_template based on the
    customer's default, overwriting what was mapped from the Quotation.
    This hook runs on before_save to restore those values.
    """
    if doc.docstatus != 0 or not doc.is_new():
        return

    # Find linked Quotation from items
    quotation_name = None
    for item in doc.items:
        if item.prevdoc_docname:
            quotation_name = item.prevdoc_docname
            break

    if not quotation_name:
        return

    qt = frappe.db.get_value(
        "Quotation", quotation_name,
        ["payment_terms_template", "tc_name", "terms"],
        as_dict=True,
    )
    if not qt:
        return

    # Restore payment terms if the Quotation had them
    if qt.payment_terms_template and not doc.payment_terms_template:
        doc.payment_terms_template = qt.payment_terms_template
        # Re-fetch payment schedule from the Quotation
        qt_schedules = frappe.get_all(
            "Payment Schedule",
            filters={"parent": quotation_name, "parenttype": "Quotation"},
            fields=["payment_term", "description", "due_date", "invoice_portion", "discount_type", "discount", "mode_of_payment"],
            order_by="idx asc",
        )
        if qt_schedules:
            doc.set("payment_schedule", [])
            for ps in qt_schedules:
                doc.append("payment_schedule", {
                    "payment_term": ps.payment_term,
                    "description": ps.description,
                    "due_date": ps.due_date,
                    "invoice_portion": ps.invoice_portion,
                    "discount_type": ps.discount_type,
                    "discount": ps.discount,
                    "mode_of_payment": ps.mode_of_payment,
                    "payment_amount": flt(doc.grand_total or doc.rounded_total) * flt(ps.invoice_portion) / 100,
                })

    # Restore terms and conditions if not already set
    if qt.tc_name and not doc.tc_name:
        doc.tc_name = qt.tc_name
        doc.terms = qt.terms


# ── Server Script: "Delivery Date" ──
# DocType Event: Sales Order, After Save
def sync_delivery_date_to_items(doc, method=None):
    """Copy parent delivery_date to all child items."""
    for item in doc.items:
        item.delivery_date = doc.delivery_date


# ── Server Script: "SO submit date" ──
# DocType Event: Sales Order, After Submit (on_submit)
def set_sales_order_confirmation_date(doc, method=None):
    """Set the custom confirmation date on submit."""
    doc.db_set("custom_sales_order_confirmation_date", frappe.utils.nowdate())


# ── Server Script: "Validate Customer Company" ──
# DocType Event: Sales Order, Before Validate
def validate_customer_company(doc, method=None):
    """Ensure customer belongs to the same company on the order."""
    if doc.customer and doc.company and not doc.is_internal_customer:
        customer = frappe.get_doc("Customer", doc.customer)
        if customer.company and customer.company != doc.company:
            frappe.throw(_("Customer does not belongs to company"))


# ── Server Script: "SO - Item Tax Template" ──
# DocType Event: Sales Order, Before Save
def validate_item_tax_template(doc, method=None):
    """Auto-fill Item Tax Template from the Item's configured taxes, then
    hard-require it for Avientek Electronics Trading PVT. LTD (non-Overseas).

    The old version only threw an error if the field was blank — but most
    items have 6+ valid templates configured on the Item master already.
    Now we try to auto-pick the right one (matching the company
    abbreviation, e.g. 'GST 18% - AETPL' for AETPL) and only throw when
    the Item genuinely has no tax template to pick from."""
    from avientek.events.utils import autofill_item_tax_template
    required = None
    if doc.company == "Avientek Electronics Trading PVT. LTD" and doc.tax_category != "Overseas":
        required = "Avientek Electronics Trading PVT. LTD"
    autofill_item_tax_template(doc, required_company=required)


# ── Server Script: "Validate exchange rate v2" ──
# DocType Event: Sales Order, Before Validate
def validate_exchange_rate_v2(doc, method=None):
    """Warn if exchange rate does not match the latest system Currency Exchange rate."""
    if doc.currency == doc.price_list_currency:
        if doc.conversion_rate and doc.plc_conversion_rate:
            if doc.conversion_rate != doc.plc_conversion_rate:
                doc.plc_conversion_rate = doc.conversion_rate
            else:
                company_default_currency = frappe.db.get_value(
                    "Company", doc.company, "default_currency"
                )

                exc_rate = None
                entries = frappe.get_all(
                    "Currency Exchange",
                    fields=["exchange_rate"],
                    filters=[
                        ["date", "<=", frappe.utils.get_datetime_str(doc.transaction_date)],
                        ["from_currency", "=", doc.currency],
                        ["to_currency", "=", company_default_currency],
                    ],
                    order_by="date desc",
                    limit=1,
                )

                if entries:
                    exc_rate = flt(entries[0].exchange_rate)

                if exc_rate is None:
                    frappe.msgprint(
                        _("No Currency Exchange rate found for {0} -> {1} on or before {2}").format(
                            doc.currency, company_default_currency, doc.transaction_date
                        ),
                        indicator="orange",
                    )
                else:
                    if abs(exc_rate - doc.conversion_rate) > 0.000001 or abs(exc_rate - doc.plc_conversion_rate) > 0.000001:
                        frappe.msgprint(
                            _("Exchange rate does not match the system rate. Please review."),
                            indicator="orange",
                        )


# ── Server Script: "Validate Exchange Rate" (DISABLED) ──
# Superseded by validate_exchange_rate_v2 above.
# def validate_exchange_rate(doc, method=None):
#     if doc.currency == doc.price_list_currency:
#         if doc.conversion_rate and doc.plc_conversion_rate:
#             if doc.conversion_rate != doc.plc_conversion_rate:
#                 doc.plc_conversion_rate = doc.conversion_rate
#             else:
#                 company_default_currency = frappe.db.get_value("Company", doc.company, "default_currency")
#                 entries = frappe.get_all("Currency Exchange", fields=["exchange_rate"],
#                     filters=[["date", "<=", frappe.utils.get_datetime_str(doc.transaction_date)],
#                              ["from_currency", "=", doc.currency],
#                              ["to_currency", "=", company_default_currency]],
#                     order_by="date desc", limit=1)
#                 if entries:
#                     exc_rate = frappe.utils.flt(entries[0].exchange_rate)
#                 if (exc_rate != doc.conversion_rate) or (exc_rate != doc.plc_conversion_rate):
#                     frappe.throw("Exchange rate is wrong!")


# ── Server Script: "Auto Share Order with Parent Sales Users" (DISABLED) ──
# DocType Event: Sales Order, After Save
# NOTE: This script was disabled in the site. Auto-sharing is handled client-side.
# def auto_share_with_parent_sales_users(doc, method=None):
#     ... (see server_client_scripts_backup.json for full logic)


@frappe.whitelist()
def create_proforma_invoice(source_name, target_doc=None, args=None):
	target_doc = get_mapped_doc(
		"Sales Order",
		source_name,
		{
			"Sales Order": {
				"doctype": "Avientek Proforma Invoice",
			},
			"Sales Order Item": {
				"doctype": "Proforma Invoice Item",
				"field_map": [
					# ["qty", "quantity"]
					# ["name","purchase_order_item"]
				],
				# "postprocess":update_item,
				# "condition": lambda doc: abs(doc.received_qty) <= abs(doc.qty),
			},
			"Sales Taxes and Charges":{
				"doctype":"Sales Taxes and Charges",
			}
		},
		target_doc,
	)
	return target_doc


def update_eta_in_po(doc, method):
	for item in doc.items:
		if item.purchase_order:
			po = frappe.get_doc("Purchase Order", item.purchase_order)
			updated = False
			for po_item in po.items:
				if po_item.item_code == item.item_code:
					po_item.db_set("avientek_eta", item.avientek_eta)
					po_item.db_set("eta", item.eta)
					po.db_set("avientek_eta",item.avientek_eta)
					updated = True
			if updated:
				po.save()
