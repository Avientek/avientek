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
        # Set required party fields (previously missing — caused errors on save)
        target.payment_type = "Pay"
        target.party_type = "Supplier"
        target.party = source.supplier
        target.party_name = source.supplier_name or source.supplier
        target.posting_date = frappe.utils.nowdate()

        # Attachment PDFs (PO, Quotation) used to be saved here via save_file
        # with dt=target.doctype, dn=target.name — but `target.name` is blank
        # during the mapping postprocess (new doc not saved yet). Frappe
        # returned "Attached To Name must be a string or an integer" and
        # the whole Create action failed. The attachment_html variable it
        # assembled was never used on the target either, so dropping the
        # whole block. Attachments can be added after save.

        purchase_order = source.items[0].purchase_order if source.items else ""

        # Add row to Payment References. PaymentRequestReference schema
        # has: reference_doctype, reference_name, grand_total,
        # base_grand_total, outstanding_amount, base_outstanding_amount,
        # exchange_rate, invoice_date, currency, document_reference,
        # remarks, due_date. It does NOT have payment_amount or
        # total_amount — those fields previously tripped the mapper.
        exchange_rate = source.conversion_rate or 1
        os_company = source.outstanding_amount or 0  # in company currency (AED)
        os_invoice = os_company / exchange_rate if exchange_rate else os_company

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

        # Parent totals — use only fields the child row actually has.
        target.total_outstanding_amount = sum((row.outstanding_amount or 0) for row in target.payment_references)
        target.total_payment_amount = 0
        target.total_amount = sum((row.grand_total or 0) for row in target.payment_references)

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
