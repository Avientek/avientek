# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt

"""Advance Gross Profit — wraps ERPNext's Gross Profit report and adds:
    - Reward Expense   (per Sales Invoice, from booked JV)
    - Incentive Expense
    - Net Profit       (= Gross Profit − Reward Expense − Incentive Expense)
    - Net Profit %     (= Net Profit / Selling Amount × 100)

Source of truth: the Journal Entry posted by
avientek.events.sales_invoice_reward_incentive.book_reward_incentive_jv
on Sales Invoice submit. The JV's Account rows carry
reference_type='Sales Invoice', reference_name=<si_name> on the debit
expense legs, which is what we group by here.

Reward / Incentive expense accounts are the same ones configured in
Avientek Settings → Company Account Mapping. We read them once per
report run.

Group-by handling (v1):
    Group By "Invoice"     — exact per-SI breakdown.
    Group By anything else — Reward / Incentive / Net columns show 0
                             (the upstream rows don't carry SI names).
                             The JS surfaces a description on those
                             columns explaining this.
"""

from collections import defaultdict

import frappe
from frappe.utils import flt

from erpnext.accounts.report.gross_profit.gross_profit import execute as upstream_execute


# ── public ────────────────────────────────────────────────────────────

def execute(filters=None):
    columns, data, *rest = upstream_execute(filters or frappe._dict())

    # Build map: si_name -> {"reward": x, "incentive": y}
    si_map = _build_si_expense_map(filters or frappe._dict())

    # Add the four new columns once, after gross_profit_percent if found.
    columns = _augment_columns(columns)

    # Walk rows. Upstream returns dicts (and occasionally lists for header
    # rows in some Frappe versions); leave non-dict rows untouched.
    for row in data:
        if not isinstance(row, dict):
            continue

        si_name = _extract_si_name(row)
        rec = si_map.get(si_name) if si_name else None
        reward = flt((rec or {}).get("reward"))
        incentive = flt((rec or {}).get("incentive"))

        gp = flt(row.get("gross_profit"))
        sa = flt(row.get("selling_amount") or row.get("base_amount"))

        net_profit = gp - reward - incentive
        net_profit_pct = (net_profit / sa * 100) if sa else 0

        row["reward_expense"] = reward
        row["incentive_expense"] = incentive
        row["net_profit"] = net_profit
        row["net_profit_pct"] = flt(net_profit_pct, 2)

    return (columns, data, *rest) if rest else (columns, data)


# ── internals ─────────────────────────────────────────────────────────

def _augment_columns(columns):
    """Append four new columns. Inserted after 'gross_profit_percent'
    if present, else at end."""
    new_cols = [
        {
            "label": "Reward Expense",
            "fieldname": "reward_expense",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 130,
        },
        {
            "label": "Incentive Expense",
            "fieldname": "incentive_expense",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": "Net Profit",
            "fieldname": "net_profit",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 130,
        },
        {
            "label": "Net Profit %",
            "fieldname": "net_profit_pct",
            "fieldtype": "Percent",
            "width": 110,
        },
    ]

    insert_after_idx = None
    for i, c in enumerate(columns or []):
        if isinstance(c, dict) and c.get("fieldname") in ("gross_profit_percent", "gross_profit_%"):
            insert_after_idx = i + 1
            break

    if insert_after_idx is None:
        return list(columns or []) + new_cols
    return list(columns[:insert_after_idx]) + new_cols + list(columns[insert_after_idx:])


def _extract_si_name(row):
    """Find the Sales Invoice name on a row from upstream Gross Profit.
    Invoice-grouping mode uses 'invoice_or_item' for the header row and
    'parent_invoice' for child item rows."""
    for fn in ("parent_invoice", "invoice_or_item", "sales_invoice", "name"):
        v = row.get(fn)
        if isinstance(v, str) and v and frappe.db.exists("Sales Invoice", v):
            return v
    return None


def _build_si_expense_map(filters):
    """Sum debit_in_account_currency from Journal Entry Account rows
    where reference_type='Sales Invoice' and account is one of the
    Reward / Incentive expense accounts configured in Avientek Settings.

    Scoped by company + posting_date range from the report filters so the
    SQL doesn't scan the whole JV history.

    Returns: {si_name: {"reward": x, "incentive": y}}
    """
    company = filters.get("company") if isinstance(filters, dict) else getattr(filters, "company", None)
    from_date = filters.get("from_date") if isinstance(filters, dict) else getattr(filters, "from_date", None)
    to_date = filters.get("to_date") if isinstance(filters, dict) else getattr(filters, "to_date", None)

    reward_acct, incentive_acct = _expense_accounts_for_company(company)
    if not reward_acct and not incentive_acct:
        return {}

    accts = [a for a in (reward_acct, incentive_acct) if a]
    placeholders = ", ".join(["%s"] * len(accts))

    # Link JV → Sales Invoice via je.cheque_no (set to SI.name by
    # book_reward_incentive_jv). One-way link policy: we don't store any
    # SI ref on the JV other than cheque_no + user_remark. SI side has
    # custom_reward_incentive_jv which is the canonical pointer the
    # other direction.
    #
    # We don't use jea.reference_name because ERPNext's JV validator
    # forbids setting reference_type=Sales Invoice on non-Receivable
    # account rows.
    where = [
        "jea.parenttype = 'Journal Entry'",
        "je.docstatus = 1",
        f"jea.account IN ({placeholders})",
        "jea.debit_in_account_currency > 0",
        "(je.cheque_no IS NOT NULL AND je.cheque_no != '')",
    ]
    params = list(accts)

    if company:
        where.append("je.company = %s")
        params.append(company)
    if from_date:
        where.append("je.posting_date >= %s")
        params.append(from_date)
    if to_date:
        where.append("je.posting_date <= %s")
        params.append(to_date)

    rows = frappe.db.sql(
        f"""
        SELECT je.cheque_no AS si,
               jea.account, jea.debit_in_account_currency AS amt
        FROM `tabJournal Entry Account` jea
        INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
        WHERE {' AND '.join(where)}
        """,
        params, as_dict=True,
    )

    out = defaultdict(lambda: {"reward": 0.0, "incentive": 0.0})
    for r in rows:
        bucket = "reward" if r["account"] == reward_acct else "incentive"
        out[r["si"]][bucket] += flt(r["amt"])
    return dict(out)


def _expense_accounts_for_company(company):
    """Return (reward_expense_account, incentive_expense_account) for
    the given company from Avientek Settings → Company Account Mapping.
    Returns (None, None) if not configured."""
    if not company:
        return None, None
    try:
        s = frappe.get_single("Avientek Settings")
    except Exception:
        return None, None
    for r in (s.get("reward_incentive_company_accounts") or []):
        if r.get("company") == company:
            return r.get("reward_expense_account"), r.get("incentive_expense_account")
    return None, None
