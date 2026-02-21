import frappe
from frappe.utils import flt
from frappe.model.mapper import get_mapped_doc

def create_incentive_journal_entry(doc, method):
    """
    Sales Invoice → on_submit

    • Calculate proportional incentive from Sales Order
    • Convert to company currency using plc_conversion_rate
    • Create Journal Entry if not already exists
    """

    # ─────────────────────────── 1) Calculate proportional incentive from Sales Order
    total_inv_incentive = 0

    for inv_item in doc.items:
        if inv_item.sales_order and inv_item.so_detail:
            so_item = frappe.db.get_value(
                "Sales Order Item",
                inv_item.so_detail,
                ["qty", "custom_incentive_value"],  # assuming this field is on SO Item
                as_dict=True
            )
            if so_item and flt(so_item.qty) > 0:
                proportion = flt(inv_item.qty) / flt(so_item.qty)
                proportional_incentive = flt(so_item.custom_incentive_value) * proportion
                total_inv_incentive += flt(proportional_incentive)

    if total_inv_incentive <= 0.001:
        return

    # ─────────────────────────── 2) Idempotency check
    if frappe.db.exists(
        "Journal Entry Account",
        {
            "reference_type": "Sales Invoice",
            "reference_name": doc.name,
            "account": ["in", ["Sales Commission", "Sales Commission Payable"]],
        },
    ):
        return

    # ─────────────────────────── 3) Convert using plc_conversion_rate
    company_currency = frappe.get_cached_value("Company", doc.company, "default_currency")

    amount_company_cur = total_inv_incentive
    if doc.currency != company_currency:
        rate = flt(doc.plc_conversion_rate)
        if not rate:
            frappe.throw(
                "plc_conversion_rate is missing on this Sales Invoice.\n"
                "Enter the correct rate (e.g. 3.6725 for USD → AED) and resubmit."
            )
        amount_company_cur = flt(total_inv_incentive * rate, 2)

    # ─────────────────────────── 4) Fetch accounts
    def account_named(acc_name):
        acc = frappe.db.get_value(
            "Account", {"account_name": acc_name, "company": doc.company}, "name"
        )
        if not acc:
            frappe.throw(f"Account '{acc_name}' not found for company {doc.company}.")
        return acc

    debit_acc  = account_named("Sales Commission")
    credit_acc = account_named("Sales Commission Payable")

    # ─────────────────────────── 5) Create & Submit Journal Entry
    je = frappe.new_doc("Journal Entry")
    je.voucher_type  = "Journal Entry"
    je.company       = doc.company
    je.posting_date  = doc.posting_date
    je.user_remark   = f"Incentive payable for Sales Invoice {doc.name}"
    je.custom_sales_invoice = doc.name

    je.append(
        "accounts",
        {
            "account": debit_acc,
            "debit_in_account_currency": amount_company_cur,
            "credit_in_account_currency": 0,
        },
    )
    je.append(
        "accounts",
        {
            "account": credit_acc,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": amount_company_cur,
        },
    )

    je.insert(ignore_permissions=True)
    je.submit()


@frappe.whitelist()
def create_payment_request(source_name, target_doc=None, args=None):
    def set_missing_values(source, target):
        target.party_type = "Customer"
        target.party = source.customer
        target.party_name = source.customer_name

        ref_type = "Credit Note" if source.is_return else "Sales Invoice"
        exchange_rate = flt(source.conversion_rate) or 1
        os_company = flt(source.outstanding_amount) or 0
        os_invoice = os_company / exchange_rate if exchange_rate else os_company

        target.append("payment_references", {
            "reference_doctype": ref_type,
            "reference_name": source.name,
            "grand_total": flt(source.grand_total),
            "base_grand_total": flt(source.base_grand_total),
            "outstanding_amount": abs(os_invoice),
            "base_outstanding_amount": abs(os_company),
            "invoice_date": source.posting_date,
            "due_date": source.due_date,
            "currency": source.currency,
            "exchange_rate": exchange_rate,
            "is_return": source.is_return,
            "return_against": source.return_against,
        })

        total_outstanding = sum(abs(flt(row.outstanding_amount)) for row in target.payment_references)
        target.total_outstanding_amount = total_outstanding
        target.total_payment_amount = 0
        target.total_amount = abs(flt(source.grand_total))

    target_doc = get_mapped_doc(
        "Sales Invoice",
        source_name,
        {
            "Sales Invoice": {
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
