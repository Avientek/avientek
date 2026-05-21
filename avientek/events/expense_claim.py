import frappe
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt

@frappe.whitelist()
def create_payment_request(source_name, target_doc=None, args=None):
    def set_missing_values(source, target):
        target.party_type = "Employee"
        target.party = source.employee
        target.party_name = source.employee_name

        outstanding = flt(source.total_sanctioned_amount) - flt(source.total_amount_reimbursed)

        # Sammish 2026-05-21 (Jithin escalation): Create → Payment Request
        # Form on an Expense Claim was putting the Frappe EC doc name into
        # `reference_name` and leaving `document_reference` empty. That
        # broke the print + Combined PDF resolver. Canonical contract:
        #   - reference_name      = "" (EC has no third-party bill_no)
        #   - document_reference  = Frappe doc name of the EC (canonical
        #                           pointer used by every downstream
        #                           renderer / resolver)
        target.append("payment_references", {
            "reference_doctype": "Expense Claim",
            "reference_name": "",
            "bill_no": "",
            "grand_total": flt(source.total_sanctioned_amount),
            "base_grand_total": flt(source.total_sanctioned_amount),
            "outstanding_amount": outstanding,
            "base_outstanding_amount": outstanding,
            "invoice_date": source.posting_date,
            "document_reference": source.name,
            "currency": frappe.get_cached_value("Company", source.company, "default_currency"),
            "exchange_rate": 1,
        })

        target.total_outstanding_amount = outstanding
        target.total_payment_amount = 0
        target.total_amount = flt(source.total_sanctioned_amount)

    target_doc = get_mapped_doc(
        "Expense Claim",
        source_name,
        {
            "Expense Claim": {
                "doctype": "Payment Request Form",
                "field_map": {
                    "company": "company",
                    "department": "department",
                    "cost_center": "cost_center",
                },
            },
        },
        target_doc,
        postprocess=set_missing_values,
    )

    return target_doc
