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


# Rahul 2026-05-26 (GRN-LTD-26-00725 / I003892): PR submitted in USD
# with item rate $60.16 (manual override from buyer-negotiated rate).
# When PI was generated via "Create > Purchase Invoice" from PR, the
# item rate flipped to $64.66 and PLE rate changed from 88.7 to 93.
# Root cause: make_purchase_invoice in ERPNext copies the rate via
# get_mapped_doc, then set_missing_values runs on the new PI which
# re-fetches price_list_rate from Item Price master and re-applies the
# current plc_conversion_rate (PLE). Any manual override on the PR is
# silently lost — buyer's negotiated rate replaced by master rate
# recomputed at current PLE.
#
# Fix: on PI validate, for any row that has pr_detail set, force the
# rate and pricing fields back to what the source PR row has stored.
# Idempotent — re-running yields the same values.
_PR_PRICING_FIELDS = [
    "rate",
    "price_list_rate",
    "discount_percentage",
    "discount_amount",
    "margin_type",
    "margin_rate_or_amount",
    "rate_with_margin",
    "base_rate",
    "base_price_list_rate",
    "base_rate_with_margin",
    "net_rate",
    "base_net_rate",
]


def _fetch_pr_pricing(pr_details):
    """Bulk-read pricing fields for a list of Purchase Receipt Item names.

    Returns {pr_detail_name: {field: value}}. Missing PR rows are silently
    skipped. Shared between the server-side validate hook and the
    client-side whitelisted endpoint so both paths produce the same
    locked values.
    """
    if not pr_details:
        return {}
    rows = frappe.get_all(
        "Purchase Receipt Item",
        filters={"name": ("in", list(pr_details))},
        fields=["name"] + _PR_PRICING_FIELDS,
    )
    return {r["name"]: {k: r[k] for k in _PR_PRICING_FIELDS} for r in rows}


def preserve_pr_rate(doc, method=None):
    """Lock PI item rate (and pricing fields) to the source PR row.

    Prevents ERPNext's set_missing_values from recalculating rates
    when the PLE drifts between PR and PI dates, especially for
    foreign-currency transactions.

    Skips returns (Debit Notes) — those have separate flows.
    """
    if doc.is_return:
        return

    pr_details = [it.pr_detail for it in (doc.items or []) if it.get("pr_detail")]
    if not pr_details:
        return
    pricing = _fetch_pr_pricing(pr_details)

    for item in (doc.items or []):
        pr_row = pricing.get(item.get("pr_detail"))
        if not pr_row:
            continue
        for k, v in pr_row.items():
            if v is None:
                continue
            if item.get(k) != v:
                item.set(k, v)


@frappe.whitelist()
def get_pr_locked_pricing(pr_details):
    """Client-side companion to preserve_pr_rate.

    Sridhar/Rahul 2026-06-10: even with the validate hook restoring rates
    on save, the UI between PR→PI conversion and save showed scrambled
    rates (sometimes negative — e.g. row 1 $-164.00, row 2 $570.00 from
    a PR where both rows were $665.00). Cause: changing `posting_date`
    on the new PI fires ERPNext's posting_date → set_exchange_rate chain
    which recomputes per-row rate using the *new* PLE plus any cached
    discount_amount, producing nonsense numbers in the grid.

    The PI's purchase_invoice.js calls this on posting_date /
    conversion_rate / currency / bill_date change so the locked rates
    are restored in the UI instantly — matching what the validate hook
    would store on save.

    Args:
        pr_details: JSON-encoded list of Purchase Receipt Item names
                    (or a Python list; auto-decode for safety).

    Returns:
        Dict {pr_detail_name: {pricing_field: value}}. Missing/stale
        pr_details are silently dropped.
    """
    if isinstance(pr_details, str):
        try:
            pr_details = frappe.parse_json(pr_details) or []
        except Exception:
            pr_details = []
    pr_details = [d for d in (pr_details or []) if d]
    return _fetch_pr_pricing(pr_details)


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

        exchange_rate = source.conversion_rate or 1
        os_company = source.outstanding_amount or 0  # in company currency
        os_invoice = os_company / exchange_rate if exchange_rate else os_company

        # Sammish 2026-05-21 (Jithin escalation): Create → Payment Request
        # Form on a Purchase Invoice was leaking the linked Purchase Order
        # into `document_reference` and the Frappe PI doc name into
        # `reference_name`. That violates the canonical contract
        # (established 2026-05-18, used by Combined PDF builder + print
        # template + Connections panel resolver):
        #   - reference_name      = supplier's bill_no (free text)
        #   - bill_no             = same supplier bill_no, mirrored for
        #                           list display and downstream sorting
        #   - document_reference  = Frappe doc name of the PI (canonical
        #                           system pointer)
        # Symptoms of the prior bug: "Document Reference" column showed
        # PO-FZCO-NNNN instead of the PI; print preview + Combined PDF
        # rendered the PO copy instead of the PI; Connections panel could
        # not navigate back to the PI.
        target.append("payment_references", {
            "reference_doctype": "Purchase Invoice",
            "reference_name": source.bill_no or "",
            "bill_no": source.bill_no or "",
            "grand_total": source.grand_total,
            "base_grand_total": source.base_grand_total,
            "outstanding_amount": os_invoice,
            "base_outstanding_amount": os_company,
            "invoice_date": source.bill_date or source.posting_date,
            "document_reference": source.name,
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
