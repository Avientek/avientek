import frappe
from frappe.model.mapper import get_mapped_doc

@frappe.whitelist()
def create_payment_request(source_name, target_doc=None, args=None):
    def set_single_reference(source, target):
        cost_center = source.accounts[0].cost_center if source.accounts else ""

        target.append("payment_references", {
            "reference_doctype": "Journal Entry",
            "reference_name": source.name,
            "total_amount": source.total_debit,
            "outstanding_amount": source.total_debit,
            "invoice_date": source.posting_date,
            "document_reference": source.custom_sales_invoice,
            "cost_center": cost_center
        })
        total_outstanding = sum((row.outstanding_amount or 0) for row in target.payment_references)
        target.total_outstanding_amount = total_outstanding
        total_payment = sum((row.payment_amount or 0) for row in target.payment_references)
        target.total_payment_amount = total_payment
        total_amount = sum((row.total_amount or 0) for row in target.payment_references)
        target.total_amount = total_amount
    target_doc = get_mapped_doc(
        "Journal Entry",
        source_name,
        {
            "Journal Entry": {
                "doctype": "Payment Request Form",
                # "party": "supplier"
            },
        },
        target_doc,
        postprocess=set_single_reference
    )

    return target_doc
