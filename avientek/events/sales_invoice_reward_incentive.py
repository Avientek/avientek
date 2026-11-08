"""Reward & Incentive JV booking on Sales Invoice submit / cancel.

Triggered from hooks.py:
    Sales Invoice.on_submit  → book_reward_incentive_jv
    Sales Invoice.on_cancel  → cancel_reward_incentive_jv

Behaviour:
  - Reads Avientek Settings:
      * reward_incentive_method: "Quotation Wise" | "Item Wise"
      * reward_incentive_company_accounts: child table of (company,
        reward_expense_account, reward_payable_account,
        incentive_expense_account, incentive_payable_account)
  - Derives the source Quotation by walking SI Item → Sales Order Item →
    prevdoc_docname (Quotation). Only the FIRST quote found is used —
    multi-quote SIs are not supported in v1 (rare on Avientek's flow).
  - Quotation Wise: proportion = SI grand_total / Quote grand_total.
      Reward booked  = quote.custom_total_reward_new * proportion
      Incentive book = quote.custom_total_incentive_new * proportion
  - Item Wise: per SI item, find matching Quote item by item_code,
      proportion = si_item.qty / quote_item.qty (capped at 1.0).
      Reward booked  += quote_item.reward * proportion
      Incentive book += quote_item.custom_incentive_value * proportion
  - One JV per SI:
      Dr Reward Expense   N (cost_center derived from SI)
      Dr Incentive Expense M
      Cr Reward Payable   N  (reference: Quotation)
      Cr Incentive Payable M (reference: Quotation)
      user_remark: "Reward & Incentive booking for {SI} (against {Quote})"
  - SI gets `custom_reward_incentive_jv` set to the JV name. Re-submit is
    blocked by the field already being populated. on_cancel cancels the JV.

  - Skipped silently (with a Comment for traceability) when:
      * no quote linked
      * settings missing or method not configured
      * no company account mapping for SI.company
      * computed reward + incentive both zero

  - Credit note (is_return=1, #0590): the same formula on its absolute value
    books the REVERSE JV (Dr payables, Cr expenses), capped at what is still
    booked against the quote; it is cancelled with the credit note.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt


_SI_JV_FIELD = "custom_reward_incentive_jv"


# ── public hooks ──────────────────────────────────────────────────────

def book_reward_incentive_jv(doc, method=None):
    """Sales Invoice on_submit hook."""
    if doc.docstatus != 1:
        return
    if doc.get(_SI_JV_FIELD):
        _skip(doc, f"JV {doc.get(_SI_JV_FIELD)} already booked — skipping")
        return

    settings = _load_settings(doc.company)
    if not settings:
        return  # _load_settings already logs the reason

    method_setting = settings["method"]
    accts = settings["accounts"]

    quote = _resolve_quotation_for_si(doc)
    if not quote:
        _skip(doc, "no Quotation traceable from Sales Invoice items — JV skipped")
        return

    # #0590 (Jithin 2026-11-08): a credit note reverses its share of the
    # booking. Same formula on the credit note's absolute value; Avientek's
    # credit notes are often standalone (no Return Against), so the quote is
    # found through the sales order lines exactly as for the invoice.
    is_return = bool(int(doc.get("is_return") or 0))
    if method_setting == "Item Wise":
        reward_amt, incentive_amt = _compute_itemwise(doc, quote, absolute=is_return)
    else:
        reward_amt, incentive_amt = _compute_quotationwise(doc, quote, absolute=is_return)

    # Jithin / Sammish 2026-07-17 (INV-FZCO-26-00885-1 → JV-FZCO-26-00450):
    # the Quote's reward / incentive figures are in the QUOTE's currency
    # (e.g. USD), but _post_jv books them into company-currency accounts
    # (e.g. AED) via debit_in_account_currency — so on every foreign-currency
    # quote a USD figure was posted as AED (2,840 USD booked as 2,840 AED
    # instead of AED 10,429.90). Convert to company currency with the Quote's
    # exchange rate. No-op (rate 1.0) for quotes already in company currency,
    # so existing AED bookings are unchanged.
    conversion_rate = flt(quote.get("conversion_rate")) or 1.0
    reward_amt = flt(reward_amt * conversion_rate, 2)
    incentive_amt = flt(incentive_amt * conversion_rate, 2)
    if is_return:
        # Never reverse more than is still booked against this quote.
        net = _net_booked_for_quote(quote.name, accts)
        left_reward = max(net.get(accts["reward_expense"], 0), 0)
        reward_amt = flt(min(reward_amt, left_reward), 2)
        left_incentive = max(net.get(accts["incentive_expense"], 0), 0)
        if accts["incentive_expense"] == accts["reward_expense"]:
            left_incentive -= reward_amt
        incentive_amt = flt(min(incentive_amt, max(left_incentive, 0)), 2)
    if reward_amt <= 0 and incentive_amt <= 0:
        _skip(doc, f"computed reward={reward_amt} + incentive={incentive_amt} both zero — JV skipped")
        return

    jv_name = _post_jv(doc, quote, accts, reward_amt, incentive_amt, method_setting,
                       reverse=is_return)
    if jv_name:
        frappe.db.set_value("Sales Invoice", doc.name, _SI_JV_FIELD, jv_name, update_modified=False)
        doc.db_set(_SI_JV_FIELD, jv_name, update_modified=False)
        frappe.db.commit()


def cancel_reward_incentive_jv(doc, method=None):
    """Sales Invoice on_cancel hook — reverse the booked JV."""
    jv_name = doc.get(_SI_JV_FIELD)
    if not jv_name:
        return
    if not frappe.db.exists("Journal Entry", jv_name):
        return
    try:
        jv = frappe.get_doc("Journal Entry", jv_name)
        if jv.docstatus == 1:
            jv.flags.ignore_permissions = True
            jv.cancel()
        frappe.db.set_value("Sales Invoice", doc.name, _SI_JV_FIELD, "", update_modified=False)
        doc.db_set(_SI_JV_FIELD, "", update_modified=False)
        _comment(doc, f"Cancelled reward/incentive JV {jv_name}")
    except Exception:
        frappe.log_error(
            title=f"Reward Incentive JV cancel failed for {doc.name}",
            message=frappe.get_traceback(),
        )


# ── internals ─────────────────────────────────────────────────────────

def _load_settings(company):
    """Return {'method': str, 'accounts': dict} for the given company,
    or None if the feature is not configured."""
    try:
        s = frappe.get_single("Avientek Settings")
    except Exception:
        return None

    method_setting = (s.get("reward_incentive_method") or "").strip()
    if method_setting not in ("Quotation Wise", "Item Wise"):
        return None  # feature not enabled

    rows = s.get("reward_incentive_company_accounts") or []
    accts = None
    for r in rows:
        if r.get("company") == company:
            accts = {
                "reward_expense": r.get("reward_expense_account"),
                "reward_payable": r.get("reward_payable_account"),
                "incentive_expense": r.get("incentive_expense_account"),
                "incentive_payable": r.get("incentive_payable_account"),
            }
            break

    if not accts or not all(accts.values()):
        return None

    return {"method": method_setting, "accounts": accts}


def _resolve_quotation_for_si(si_doc):
    """Walk Sales Invoice Item → Sales Order → Sales Order Item → prevdoc_docname
    to find the source Quotation. Returns the Quotation Doc, or None.
    Only the first quote is returned even if multiple SI items reference
    different SOs; v1 assumption is one quote per SI.
    """
    sales_orders = []
    for it in si_doc.items or []:
        so = it.get("sales_order")
        if so and so not in sales_orders:
            sales_orders.append(so)
    if not sales_orders:
        return None

    # Sales Order Item.prevdoc_docname is always a Quotation (no
    # prevdoc_doctype column on the child). Some rows may have it
    # blank if SO was created standalone — skip those.
    for so in sales_orders:
        qn = frappe.db.sql(
            """SELECT prevdoc_docname FROM `tabSales Order Item`
               WHERE parent = %s AND prevdoc_docname IS NOT NULL
                 AND prevdoc_docname != ''
               ORDER BY idx LIMIT 1""",
            so, pluck="prevdoc_docname",
        )
        qn = qn[0] if qn else None
        if qn and frappe.db.exists("Quotation", qn):
            return frappe.get_doc("Quotation", qn)
    return None


def _net_booked_for_quote(quote_name, accts):
    """{expense account: amount still booked} against a quote: debits minus
    credits on the submitted reward/incentive JVs of that quote (bookings and
    earlier credit-note reversals both name the quote in user_remark)."""
    rows = frappe.db.sql(
        """SELECT jea.account, SUM(jea.debit - jea.credit) AS net
           FROM `tabJournal Entry Account` jea
           JOIN `tabJournal Entry` je ON je.name = jea.parent
           WHERE je.docstatus = 1 AND je.user_remark LIKE %s
             AND jea.account IN (%s, %s)
           GROUP BY jea.account""",
        (f"%(against {quote_name})%", accts["reward_expense"], accts["incentive_expense"]),
        as_dict=True,
    )
    return {r.account: flt(r.net) for r in rows}


def _compute_quotationwise(si_doc, quote, absolute=False):
    """Method 1: proportional to SI grand_total vs Quote grand_total.

    Uses base_* (company-currency) totals so the ratio stays correct even when
    the SI and the Quote are in different currencies — comparing raw
    grand_totals across currencies would silently skew the proportion.
    Identical to the old behaviour for company-currency documents. The returned
    amounts are still in the QUOTE's currency; the caller converts them.
    """
    quote_total = flt(quote.get("base_grand_total")) or flt(quote.get("grand_total"))
    if quote_total <= 0:
        return 0.0, 0.0
    si_total = flt(si_doc.get("base_grand_total")) or flt(si_doc.get("grand_total"))
    if absolute:
        si_total = abs(si_total)
    proportion = si_total / quote_total
    if proportion <= 0:
        return 0.0, 0.0

    reward_total = flt(quote.get("custom_total_reward_new")) or _sum_item_field(quote.items, "reward")
    incentive_total = flt(quote.get("custom_total_incentive_new")) or _sum_item_field(quote.items, "custom_incentive_value")

    return (reward_total * proportion, incentive_total * proportion)


def _compute_itemwise(si_doc, quote, absolute=False):
    """Method 2: per-item allocation by qty proportion against matching Quote item."""
    # Build qty / amounts per item_code on the Quote side.
    # If multiple Quote rows have the same item_code, sum qty/reward/incentive.
    quote_by_item = defaultdict(lambda: {"qty": 0.0, "reward": 0.0, "incentive": 0.0})
    for q_it in (quote.items or []):
        ic = q_it.get("item_code")
        if not ic:
            continue
        b = quote_by_item[ic]
        b["qty"] += flt(q_it.get("qty"))
        b["reward"] += flt(q_it.get("reward"))
        b["incentive"] += flt(q_it.get("custom_incentive_value"))

    total_reward = 0.0
    total_incentive = 0.0
    for si_it in (si_doc.items or []):
        ic = si_it.get("item_code")
        if not ic or ic not in quote_by_item:
            continue
        q = quote_by_item[ic]
        if q["qty"] <= 0:
            continue
        qty = abs(flt(si_it.get("qty"))) if absolute else flt(si_it.get("qty"))
        proportion = min(qty / q["qty"], 1.0)
        if proportion <= 0:
            continue
        total_reward += q["reward"] * proportion
        total_incentive += q["incentive"] * proportion

    return total_reward, total_incentive


def _sum_item_field(items, fieldname):
    return sum(flt(it.get(fieldname)) for it in (items or []))


def _post_jv(si_doc, quote, accts, reward_amt, incentive_amt, method_setting, reverse=False):
    """Build, insert, submit the Journal Entry. Returns JV name on success.
    reverse=True (credit note): payable debited, expense credited."""
    posting_date = si_doc.posting_date
    cost_center_default = (
        frappe.db.get_value("Company", si_doc.company, "cost_center") or None
    )
    si_cost_center = None
    for it in (si_doc.items or []):
        if it.get("cost_center"):
            si_cost_center = it.cost_center
            break
    cost_center = si_cost_center or cost_center_default

    jv = frappe.new_doc("Journal Entry")
    jv.voucher_type = "Journal Entry"
    jv.posting_date = posting_date
    jv.company = si_doc.company
    # cheque_no is the only link from JV back to SI we maintain — used
    # both for traceability on the JV form AND as the join key in the
    # Advance Gross Profit report. We deliberately do NOT set
    # custom_sales_invoice (one-way link only): SI.custom_reward_incentive_jv
    # is the single source of truth, so cancel/delete operations on the
    # SI side don't need to walk back from the JV.
    jv.cheque_no = si_doc.name
    jv.cheque_date = posting_date
    jv.user_remark = (
        f"Reward & Incentive {'reversal for credit note' if reverse else 'booking for'} "
        f"{si_doc.name} (against {quote.name}) [{method_setting}]"
    )
    dr, cr = ("credit_in_account_currency", "debit_in_account_currency") if reverse \
        else ("debit_in_account_currency", "credit_in_account_currency")

    # IMPORTANT: do NOT set reference_type/reference_name on the JV
    # account rows. ERPNext's Journal Entry validator (validate_reference_doc)
    # requires that any row referencing a Sales Invoice has the same
    # Receivable account as the SI's debit_to — but our Reward / Incentive
    # legs use expense and liability accounts, not receivables. Setting
    # the reference would throw "Party / Account does not match with
    # Customer / Debit To in Sales Invoice ...".
    #
    # Traceability instead via:
    #   - jv.cheque_no = SI.name  (visible on JV form)
    #   - jv.custom_sales_invoice = SI.name (Avientek custom Link field;
    #     consumed by the JV→PRF mapper in events/journal_entry.py)
    #   - jv.user_remark mentions both SI and Quote names
    #   - The Advance Gross Profit report queries by account + SI name in
    #     a separate SQL — it doesn't need reference_type to function.
    if reward_amt > 0:
        jv.append("accounts", {
            "account": accts["reward_expense"],
            dr: reward_amt,
            "cost_center": cost_center,
        })
        jv.append("accounts", {
            "account": accts["reward_payable"],
            cr: reward_amt,
            "cost_center": cost_center,
        })
    if incentive_amt > 0:
        jv.append("accounts", {
            "account": accts["incentive_expense"],
            dr: incentive_amt,
            "cost_center": cost_center,
        })
        jv.append("accounts", {
            "account": accts["incentive_payable"],
            cr: incentive_amt,
            "cost_center": cost_center,
        })

    if not jv.accounts:
        return None

    try:
        jv.flags.ignore_permissions = True
        jv.insert(ignore_permissions=True)
        jv.submit()
        _comment(
            si_doc,
            f"Booked reward/incentive {'reversal ' if reverse else ''}JV {jv.name}: "
            f"reward={reward_amt}, incentive={incentive_amt}, against {quote.name}, "
            f"method={method_setting}",
        )
        return jv.name
    except Exception:
        frappe.log_error(
            title=f"Reward Incentive JV booking failed for {si_doc.name}",
            message=frappe.get_traceback(),
        )
        # Don't block the SI submit on JV failure — log and continue.
        _comment(si_doc, f"Reward/Incentive JV booking FAILED — see Error Log")
        return None


def _skip(doc, msg):
    _comment(doc, f"Reward/Incentive JV: {msg}")


def _comment(doc, text):
    """Post a Comment on the SI for traceability, ignoring failures."""
    try:
        doc.add_comment("Comment", text)
    except Exception:
        pass
