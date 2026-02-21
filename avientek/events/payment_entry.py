import frappe
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt

@frappe.whitelist()
def create_payment_request(source_name, target_doc=None, args=None):
    def set_missing_values(source, target):
        target.party_type = source.party_type
        target.party = source.party
        target.party_name = source.party_name

        target.append("payment_references", {
            "reference_doctype": "Payment Entry",
            "reference_name": source.name,
            "grand_total": flt(source.paid_amount),
            "base_grand_total": flt(source.base_paid_amount),
            "outstanding_amount": flt(source.unallocated_amount) or flt(source.paid_amount),
            "base_outstanding_amount": flt(source.base_paid_amount),
            "invoice_date": source.posting_date,
            "currency": source.paid_from_account_currency or source.paid_to_account_currency,
            "exchange_rate": flt(source.source_exchange_rate) or 1,
        })

        total_outstanding = sum(flt(row.outstanding_amount) for row in target.payment_references)
        target.total_outstanding_amount = total_outstanding
        target.total_payment_amount = 0
        target.total_amount = flt(source.paid_amount)

    target_doc = get_mapped_doc(
        "Payment Entry",
        source_name,
        {
            "Payment Entry": {
                "doctype": "Payment Request Form",
                "field_map": {
                    "company": "company",
                    "posting_date": "posting_date",
                    "cost_center": "cost_center",
                },
            },
        },
        target_doc,
        postprocess=set_missing_values,
    )

    return target_doc
