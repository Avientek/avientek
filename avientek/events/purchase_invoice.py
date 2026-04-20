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

        purchase_order = source.items[0].purchase_order if source.items else ""
        attachment_html = ""

        # 1. Get Purchase Invoice Attachment
        invoice_file = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": source.doctype,
                "attached_to_name": source.bill_no
            },
            fields=["file_url"],
            order_by="creation asc",
            limit=1
        )
        if invoice_file:
            attachment_html += f'<a href="{invoice_file[0]["file_url"]}" target="_blank">Invoice Attachment</a><br>'

        # 2. Generate Purchase Order PDF & attach to Payment Request
        if purchase_order:
            try:
                custom_format = "Avientek PO"
                po_pdf_data = get_pdf(frappe.get_print("Purchase Order", purchase_order, custom_format))
                po_file = save_file(
                    fname=f"{purchase_order}-Print.pdf",
                    content=po_pdf_data,
                    dt=target.doctype,
                    dn=target.name,
                    is_private=1
                )
                attachment_html += f'<a href="{po_file.file_url}" target="_blank">Purchase Order PDF</a><br>'
            except Exception as e:
                frappe.log_error(frappe.get_traceback(), "Failed to attach PO PDF")

        # 3. From Purchase Order → Sales Order → Quotation → attach Quotation PDF
        if purchase_order:
            sales_order = frappe.db.get_value("Purchase Order Item", {"parent": purchase_order}, "sales_order")
            if sales_order:
                quotation = frappe.db.get_value("Sales Order Item", {"parent": sales_order}, "prevdoc_docname")
                if quotation:
                    try:
                        custom_format = "Quotation New"
                        quotation_pdf = get_pdf(frappe.get_print("Quotation", quotation, custom_format))
                        quotation_file = save_file(
                            fname=f"{quotation}-Print.pdf",
                            content=quotation_pdf,
                            dt=target.doctype,
                            dn=target.name,
                            is_private=1
                        )
                        attachment_html += f'<a href="{quotation_file.file_url}" target="_blank">Quotation PDF</a>'
                    except Exception as e:
                        frappe.log_error(frappe.get_traceback(), "Failed to attach Quotation PDF")

        # Add row to Payment References
        exchange_rate = source.conversion_rate or 1
        os_company = source.outstanding_amount or 0  # in company currency (AED)
        os_invoice = os_company / exchange_rate if exchange_rate else os_company  # in invoice currency

        target.append("payment_references", {
            "reference_doctype": "Purchase Invoice",
            "reference_name": source.name,
            "grand_total": source.grand_total,
            "base_grand_total": source.base_grand_total,
            "outstanding_amount": os_invoice,
            "base_outstanding_amount": os_company,
            "payment_amount": 0,
            "invoice_date": source.bill_date or source.posting_date,
            "document_reference": purchase_order,
            "currency": source.currency,
            "due_date": source.due_date,
            "exchange_rate": exchange_rate,
        })

        # Set totals
        target.total_outstanding_amount = sum((row.outstanding_amount or 0) for row in target.payment_references)
        target.total_payment_amount = sum((row.payment_amount or 0) for row in target.payment_references)
        target.total_amount = sum((row.total_amount or 0) for row in target.payment_references)

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
