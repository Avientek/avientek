from frappe.utils.pdf import get_pdf
from frappe.utils.file_manager import save_file
import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc


# ── Server Script: "PI Validate supplier company" ──
# DocType Event: Purchase Invoice, Before Validate
def validate_supplier_company(doc, method=None):
    """Ensure supplier belongs to the same company on the invoice."""
    if doc.supplier and doc.company and not doc.is_internal_supplier:
        supplier = frappe.get_doc("Supplier", doc.supplier)
        if supplier.company and supplier.company != doc.company:
            frappe.throw(_("Supplier does not belongs to company"))


# ── Server Script: "PI - Item Tax Template" ──
# DocType Event: Purchase Invoice, Before Validate
def validate_item_tax_template(doc, method=None):
    """Auto-fill Item Tax Template from Item master, then hard-require
    it for Avientek Electronics Trading PVT. LTD."""
    from avientek.events.utils import autofill_item_tax_template
    required = "Avientek Electronics Trading PVT. LTD" if doc.company == "Avientek Electronics Trading PVT. LTD" else None
    autofill_item_tax_template(doc, required_company=required)


@frappe.whitelist()
def create_payment_request(source_name, target_doc=None, args=None):
    def set_single_reference(source, target):
        # Required top-level fields on Payment Request Form. `company` was
        # previously missing — the PRF form's onload then calls
        # erpnext's get_party_details(company=...) which throws with an
        # empty company and the user sees "Server error" before the form
        # even finishes loading.
        target.payment_type = "Pay"
        target.company = source.company
        target.party_type = "Supplier"
        target.party = source.supplier
        target.party_name = source.supplier_name or source.supplier
        target.posting_date = frappe.utils.nowdate()

        purchase_order = source.items[0].purchase_order if source.items else ""

        exchange_rate = source.conversion_rate or 1
        os_company = source.outstanding_amount or 0  # in company currency
        os_invoice = os_company / exchange_rate if exchange_rate else os_company

        # PaymentRequestReference schema: reference_doctype, reference_name,
        # grand_total, base_grand_total, outstanding_amount,
        # base_outstanding_amount, exchange_rate, invoice_date, currency,
        # document_reference, remarks, due_date.
        target.append("payment_references", {
            "reference_doctype": "Purchase Invoice",
            "reference_name": source.name,
            "grand_total": source.grand_total,
            "base_grand_total": source.base_grand_total,
            "outstanding_amount": os_invoice,
            "base_outstanding_amount": os_company,
            "invoice_date": source.bill_date or source.posting_date,
            "document_reference": purchase_order,
            "currency": source.currency,
            "due_date": source.due_date,
            "exchange_rate": exchange_rate,
        })

        # Parent totals — use only fields that actually exist on PRF.
        # `total_amount` was being set previously but is NOT a PRF field;
        # removed to avoid any stray validation issues.
        target.total_outstanding_amount = sum((row.outstanding_amount or 0) for row in target.payment_references)
        target.total_payment_amount = 0

    target_doc = get_mapped_doc(
        "Purchase Invoice",
        source_name,
        {
            "Purchase Invoice": {
                "doctype": "Payment Request Form",
            },
        },
        target_doc,
        postprocess=set_single_reference
    )

    return target_doc
