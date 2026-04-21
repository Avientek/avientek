import frappe
from frappe.model.mapper import get_mapped_doc


# Doctype → display-name field for building party_name correctly.
# Previously used `name`, which returns the party ID (redundant), not the
# human-readable label.
_PARTY_NAME_FIELD = {
    "Supplier": "supplier_name",
    "Customer": "customer_name",
    "Employee": "employee_name",
}


@frappe.whitelist()
def create_payment_request(source_name, target_doc=None, args=None):
    def set_single_reference(source, target):
        target.payment_type = "Pay"
        target.company = source.company
        target.posting_date = frappe.utils.nowdate()

        # Pick the first account row that carries a party — PRF needs
        # party_type + party on the parent for the onload fetch to work.
        for acc in (source.accounts or []):
            if acc.party_type and acc.party:
                target.party_type = acc.party_type
                target.party = acc.party
                name_field = _PARTY_NAME_FIELD.get(acc.party_type, "name")
                target.party_name = (
                    frappe.db.get_value(acc.party_type, acc.party, name_field)
                    or acc.party
                )
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
        # Parent totals — `total_amount` is NOT a PRF field. Removed to
        # avoid any stray "object has no attribute" edge cases.
        target.total_outstanding_amount = sum((row.outstanding_amount or 0) for row in target.payment_references)
        target.total_payment_amount = 0

    target_doc = get_mapped_doc(
        "Journal Entry",
        source_name,
        {
            "Journal Entry": {
                "doctype": "Payment Request Form",
            },
        },
        target_doc,
        postprocess=set_single_reference
    )

    return target_doc
