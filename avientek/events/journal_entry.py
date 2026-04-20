import frappe
from frappe.model.mapper import get_mapped_doc

@frappe.whitelist()
def create_payment_request(source_name, target_doc=None, args=None):
    def set_single_reference(source, target):
        cost_center = source.accounts[0].cost_center if source.accounts else ""

        # Set required party fields from first account row with party
        target.payment_type = "Pay"
        target.company = source.company
        target.posting_date = frappe.utils.nowdate()
        for acc in (source.accounts or []):
            if acc.party_type and acc.party:
                target.party_type = acc.party_type
                target.party = acc.party
                target.party_name = frappe.db.get_value(acc.party_type, acc.party, "name") or acc.party
                break

        target.append("payment_references", {
            "reference_doctype": "Journal Entry",
            "reference_name": source.name,
            "grand_total": source.total_debit,
            "base_grand_total": source.total_debit,
            "outstanding_amount": source.total_debit,
            "base_outstanding_amount": source.total_debit,
            "invoice_date": source.posting_date,
            "document_reference": source.custom_sales_invoice or "",
            "currency": frappe.db.get_value("Company", source.company, "default_currency"),
            "exchange_rate": 1,
        })
        # PaymentRequestReference has no `total_amount` field — the old
        # `row.total_amount` access was throwing the server error on
        # Create-from-JE. Sum grand_total instead.
        target.total_outstanding_amount = sum((row.outstanding_amount or 0) for row in target.payment_references)
        target.total_payment_amount = sum((row.payment_amount or 0) for row in target.payment_references)
        target.total_amount = sum((row.grand_total or 0) for row in target.payment_references)
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
