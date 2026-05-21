import frappe
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt


# ─────────────────────────────────────────────────────────────────────
# PRF status sync (Jithin 2026-05-17)
# ─────────────────────────────────────────────────────────────────────
# When a Payment Entry that has `payment_request_form` set is submitted
# or cancelled, recompute the cumulative paid amount against that PRF
# and roll its workflow_state to Processed / Partially Processed /
# Released. Multi-PE cumulative is the design — sum of every submitted
# PE keyed to the PRF, compared against PRF.total_outstanding_amount.

_PRF_PAYMENT_STATES = ("Released", "Partially Processed", "Processed")


def update_prf_status_on_pe_submit(doc, method=None):
    """Doc event: Payment Entry → on_submit / on_cancel."""
    prf_name = (doc.get("payment_request_form") or "").strip()
    if not prf_name:
        return
    if not frappe.db.exists("Payment Request Form", prf_name):
        return
    _recompute_prf_status(prf_name)


def _recompute_prf_status(prf_name):
    """Set PRF workflow_state based on cumulative paid amount.

    Only acts on PRFs already in a payment-phase state — never demotes
    a Draft/Authorised/Approved* PRF.
    """
    current_state, target_amount = frappe.db.get_value(
        "Payment Request Form",
        prf_name,
        ["workflow_state", "total_outstanding_amount"],
    ) or (None, None)

    if current_state not in _PRF_PAYMENT_STATES:
        return

    paid = (
        frappe.db.sql(
            """
            SELECT IFNULL(SUM(base_paid_amount), 0)
            FROM `tabPayment Entry`
            WHERE payment_request_form = %s
              AND docstatus = 1
            """,
            (prf_name,),
        )[0][0]
        or 0
    )

    target_amount = flt(target_amount)
    paid = flt(paid)

    if paid <= 0:
        new_state = "Released"
    elif target_amount > 0 and paid + 0.005 >= target_amount:
        # +0.005 absorbs rounding noise on multi-currency conversions.
        new_state = "Processed"
    else:
        new_state = "Partially Processed"

    if new_state != current_state:
        frappe.db.set_value(
            "Payment Request Form",
            prf_name,
            "workflow_state",
            new_state,
            update_modified=False,
        )

@frappe.whitelist()
def create_payment_request(source_name, target_doc=None, args=None):
    def set_missing_values(source, target):
        target.party_type = source.party_type
        target.party = source.party
        target.party_name = source.party_name

        # Sammish 2026-05-21 (Jithin escalation): Create → Payment Request
        # Form on a Payment Entry was putting the Frappe PE doc name into
        # `reference_name` and leaving `document_reference` empty. That
        # broke the print + Combined PDF resolver. Canonical contract:
        #   - reference_name      = "" (PE has no third-party bill_no)
        #   - document_reference  = Frappe doc name of the PE (canonical
        #                           pointer)
        target.append("payment_references", {
            "reference_doctype": "Payment Entry",
            "reference_name": "",
            "bill_no": "",
            "grand_total": flt(source.paid_amount),
            "base_grand_total": flt(source.base_paid_amount),
            "outstanding_amount": flt(source.unallocated_amount) or flt(source.paid_amount),
            "base_outstanding_amount": flt(source.base_paid_amount),
            "invoice_date": source.posting_date,
            "document_reference": source.name,
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
