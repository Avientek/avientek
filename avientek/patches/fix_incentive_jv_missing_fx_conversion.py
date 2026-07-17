"""Correct Reward & Incentive JVs booked WITHOUT currency conversion.

Bug (fixed forward in c1d473f): `book_reward_incentive_jv` posted the Quote's
reward/incentive in the QUOTE's currency (e.g. USD) straight into
company-currency (AED) accounts via `debit_in_account_currency`, with no
exchange rate. Every foreign-currency quote therefore booked an understated
JV — e.g. INV-FZCO-26-00885-1: 2,480 USD posted as 2,480 AED instead of
AED 9,107.80 (2,480 x 3.6725).

Company-currency (rate 1.0) quotes were always correct and are NOT touched.

Per affected Sales Invoice (ORDER MATTERS):
  1. Clear SI.custom_reward_incentive_jv FIRST — the SI stays submitted and
     still points at the JV, so cancelling while linked throws
     LinkExistsError. Clearing it also releases the hook's idempotency guard.
  2. Cancel the understated JV (docstatus 1 -> 2). It is CANCELLED, never
     deleted — the document stays for audit and ERPNext posts the reversing
     GL entries.
  3. Re-invoke `book_reward_incentive_jv` — now running the FIXED code — which
     posts a NEW JV at the correct converted amount, same posting date and
     accounts.

Safety:
  * Idempotent — an SI whose JV already matches the corrected figure is
    skipped, so re-running is a no-op.
  * Only foreign-currency (conversion_rate != 1) SIs with a live (docstatus=1)
    JV are considered.
  * Per-SI error isolation: a failure (e.g. a CLOSED accounting period blocking
    the cancel) is logged and the remaining SIs still process.
  * Prints a full old -> new report to the migrate log.

⚠️ This reverses and re-posts submitted journal entries. The Sales Commission
Payable balance will rise (correctly — it was understated ~3.67x). Deploy only
once Accounts have approved AND confirmed the posting periods are open.
Audit (read-only, changes nothing):
    bench --site <site> execute avientek.scripts.audit_incentive_fx_exposure.run
"""

import frappe
from frappe.utils import flt

from avientek.events.sales_invoice_reward_incentive import (
    _compute_itemwise,
    _compute_quotationwise,
    _load_settings,
    _resolve_quotation_for_si,
    book_reward_incentive_jv,
)

_SI_JV_FIELD = "custom_reward_incentive_jv"


def _correct_amount(si, quote):
    """The amount the FIXED hook would book, in company currency."""
    settings = _load_settings(si.company)
    if not settings:
        return None
    if settings["method"] == "Item Wise":
        reward, incentive = _compute_itemwise(si, quote)
    else:
        reward, incentive = _compute_quotationwise(si, quote)
    rate = flt(quote.get("conversion_rate")) or 1.0
    return flt((flt(reward) + flt(incentive)) * rate, 2)


def execute():
    sis = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, _SI_JV_FIELD: ["not in", ("", None)]},
        fields=["name"],
        order_by="posting_date",
    )

    fixed = skipped = failed = 0
    total_delta = 0.0

    for row in sis:
        si = frappe.get_doc("Sales Invoice", row.name)
        old_jv = si.get(_SI_JV_FIELD)
        jv = frappe.db.get_value(
            "Journal Entry", old_jv, ["docstatus", "total_debit"], as_dict=True
        )
        if not jv or jv.docstatus != 1:
            continue  # missing or already cancelled

        quote = _resolve_quotation_for_si(si)
        if not quote:
            continue

        rate = flt(quote.get("conversion_rate")) or 1.0
        if abs(rate - 1.0) < 1e-9:
            continue  # company currency — was always correct

        correct = _correct_amount(si, quote)
        old_total = flt(jv.total_debit, 2)
        if not correct or correct <= 0 or abs(correct - old_total) < 0.01:
            skipped += 1  # already correct (e.g. patch re-run) — idempotent
            continue

        try:
            # ORDER MATTERS. We must UNLINK before cancelling: the SI stays
            # submitted and still points at the JV via custom_reward_incentive_jv,
            # so Frappe's link check throws
            #   LinkExistsError: Cannot delete or cancel because Journal Entry X
            #   is linked with Sales Invoice Y
            # (cancel_reward_incentive_jv cancels first then clears — correct for
            # the SI-cancel flow, wrong here — and it swallows the error, which
            # would leave the JV live and the link cleared.)
            frappe.db.set_value(
                "Sales Invoice", si.name, _SI_JV_FIELD, "", update_modified=False
            )
            frappe.db.commit()  # link must be gone before the cancel check reads it

            jv_doc = frappe.get_doc("Journal Entry", old_jv)
            jv_doc.flags.ignore_permissions = True
            jv_doc.cancel()

            si.reload()
            book_reward_incentive_jv(si)  # re-book with the fixed code
            si.reload()
            new_jv = si.get(_SI_JV_FIELD)
            new_total = flt(
                frappe.db.get_value("Journal Entry", new_jv, "total_debit") or 0, 2
            )
            frappe.db.commit()

            fixed += 1
            total_delta += new_total - old_total
            print(
                f"  [fixed] {si.name}: {old_jv} {old_total:,.2f} -> "
                f"{new_jv} {new_total:,.2f}  (+{new_total - old_total:,.2f})"
            )
        except Exception:
            failed += 1
            frappe.db.rollback()
            frappe.log_error(
                title=f"Incentive JV FX correction failed for {si.name}",
                message=frappe.get_traceback(),
            )
            print(f"  [FAILED] {si.name} — see Error Log (period closed?)")

    print(
        f"[fix_incentive_jv_missing_fx_conversion] fixed={fixed} "
        f"already_correct={skipped} failed={failed} "
        f"total_correction=+{total_delta:,.2f}"
    )
