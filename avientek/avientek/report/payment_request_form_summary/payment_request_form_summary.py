# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Payment Request Form Summary — consolidated view of every PRF.
#
# Column structure (Jithin's 2026-05-23 template applied):
#   PRF Amount                 — document currency value (issued side
#                                for IT; sum of child outstanding
#                                amounts for Pay/Receive/Advance Pay)
#   PRF-Amount Company Currency — base/company-currency equivalent
#                                (always shown, no opt-in toggle)
#   Amount                     — receiving_amount for IT rows; blank
#                                for non-IT (no destination side)
#   PRF-Currency               — issued/document currency code
#
# IT base_net_amount fallback ladder:
#   1. receiving_currency = company_default → receiving_amount
#   2. issued_currency    = company_default → issued_amount
#   3. cross-currency (neither side matches) → issued_amount × FX
#      via frappe.utils.get_exchange_rate(issued_currency, company_default, posting_date)
#
# Pay/Receive/Advance Pay base_net_amount:
#   sum of Payment Request Reference.base_outstanding_amount (already
#   in company currency from PRF save).

import frappe
from frappe import _
from frappe.utils import flt
from erpnext.setup.utils import get_exchange_rate


def execute(filters=None):
    filters = frappe._dict(filters or {})
    cols = _columns()
    rows = _data(filters)
    _backfill_cross_currency_base(rows)
    return cols, rows


def _columns():
    return [
        {"label": _("ID"), "fieldname": "name", "fieldtype": "Link",
         "options": "Payment Request Form", "width": 160},
        {"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
        {"label": _("Status"), "fieldname": "workflow_state", "fieldtype": "Data", "width": 140},
        {"label": _("Payment Type"), "fieldname": "payment_type", "fieldtype": "Data", "width": 120},
        {"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Link",
         "options": "DocType", "width": 100},
        {"label": _("Party"), "fieldname": "party", "fieldtype": "Dynamic Link",
         "options": "party_type", "width": 160},
        {"label": _("Party Name"), "fieldname": "party_name", "fieldtype": "Data", "width": 200},
        # Renamed columns per Jithin 2026-05-23 template:
        {"label": _("PRF Amount"), "fieldname": "net_amount", "fieldtype": "Currency",
         "options": "currency_code", "width": 140},
        {"label": _("PRF-Amount Company Currency"), "fieldname": "base_net_amount",
         "fieldtype": "Currency", "options": "base_currency_code", "width": 170},
        # NEW: Amount = receiving_amount for IT rows (destination side).
        {"label": _("Amount"), "fieldname": "receiving_amount", "fieldtype": "Currency",
         "options": "receiving_currency", "width": 140},
        {"label": _("PRF-Currency"), "fieldname": "currency_code", "fieldtype": "Link",
         "options": "Currency", "width": 100},
        # NEW: Receiving Currency shown right next to Amount so the IT
        # destination leg is unambiguous in cross-currency transfers.
        {"label": _("Receiving Currency"), "fieldname": "receiving_currency",
         "fieldtype": "Link", "options": "Currency", "width": 100},
        {"label": _("Base Currency"), "fieldname": "base_currency_code",
         "fieldtype": "Link", "options": "Currency", "width": 90},
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link",
         "options": "Company", "width": 180},
        {"label": _("Department"), "fieldname": "department", "fieldtype": "Link",
         "options": "Department", "width": 140},
        {"label": _("Payment Mode"), "fieldname": "payment_mode", "fieldtype": "Link",
         "options": "Mode of Payment", "width": 130},
        {"label": _("Issued Bank"), "fieldname": "issued_bank", "fieldtype": "Link",
         "options": "Bank Account", "width": 160},
        {"label": _("Beneficiary Name"), "fieldname": "beneficiary_name",
         "fieldtype": "Data", "width": 180},
        {"label": _("Created By"), "fieldname": "owner", "fieldtype": "Link",
         "options": "User", "width": 160},
    ]


def _data(filters):
    where, params = _build_conditions(filters)
    sql = """
        SELECT
            prf.name,
            prf.posting_date,
            prf.workflow_state,
            prf.payment_type,
            prf.party_type,
            prf.party,
            prf.party_name,
            prf.company,
            prf.department,
            prf.payment_mode,
            prf.issued_bank,
            prf.owner,

            /* PRF Amount — document currency value.
               IT uses issued_amount; others sum child.outstanding_amount. */
            CASE
                WHEN prf.payment_type = 'Internal Transfer' THEN prf.issued_amount
                ELSE IFNULL((
                    SELECT SUM(pr.outstanding_amount)
                    FROM `tabPayment Request Reference` pr
                    WHERE pr.parent = prf.name
                ), 0)
            END AS net_amount,

            /* PRF-Currency — document currency code.
               IT uses issued_currency; others pick MAX(child.currency) for
               single-currency PRFs (the common case). */
            CASE
                WHEN prf.payment_type = 'Internal Transfer' THEN prf.issued_currency
                ELSE IFNULL((
                    SELECT MAX(pr.currency)
                    FROM `tabPayment Request Reference` pr
                    WHERE pr.parent = prf.name
                      AND pr.currency IS NOT NULL
                      AND pr.currency != ''
                ), prf.currency)
            END AS currency_code,

            /* Amount — receiving_amount for IT, NULL for non-IT.
               Non-IT rows have no destination leg. */
            CASE
                WHEN prf.payment_type = 'Internal Transfer'
                    THEN prf.receiving_amount
                ELSE NULL
            END AS receiving_amount,
            CASE
                WHEN prf.payment_type = 'Internal Transfer'
                    THEN prf.receiving_currency
                ELSE NULL
            END AS receiving_currency,

            /* PRF-Amount Company Currency — base/company-currency value.
               IT ladder: receiving matches → receiving_amount;
                          issued matches    → issued_amount;
                          neither matches   → NULL (filled in Python
                          via get_exchange_rate). */
            CASE
                WHEN prf.payment_type = 'Internal Transfer' THEN
                    CASE
                        WHEN prf.receiving_currency =
                            (SELECT default_currency FROM `tabCompany` WHERE name = prf.company)
                            THEN prf.receiving_amount
                        WHEN prf.issued_currency =
                            (SELECT default_currency FROM `tabCompany` WHERE name = prf.company)
                            THEN prf.issued_amount
                        ELSE NULL
                    END
                ELSE IFNULL((
                    SELECT SUM(pr.base_outstanding_amount)
                    FROM `tabPayment Request Reference` pr
                    WHERE pr.parent = prf.name
                ), 0)
            END AS base_net_amount,
            (SELECT default_currency FROM `tabCompany` WHERE name = prf.company)
                AS base_currency_code,

            /* Beneficiary Name — pulled from the linked supplier bank
               account when set (custom field added 2026-05-21). */
            (
                SELECT ba.beneficiary_name
                FROM `tabBank Account` ba
                WHERE ba.name = prf.supplier_bank_account
                LIMIT 1
            ) AS beneficiary_name

        FROM `tabPayment Request Form` prf
        WHERE prf.docstatus < 2
            {where}
        ORDER BY prf.posting_date DESC, prf.name DESC
    """.format(where=where)
    return frappe.db.sql(sql, params, as_dict=True)


def _backfill_cross_currency_base(rows):
    """Post-SQL: for Internal Transfer rows where neither issued nor
    receiving currency matches the company default, compute the base
    equivalent via frappe.utils.get_exchange_rate(issued, base, date).

    Done in Python (not SQL) because Currency Exchange lookups span
    multiple tables and Frappe has utility helpers that fall back to
    Exchange Rate Settings + 1.0 sensibly when no rate row exists.
    """
    for r in rows:
        if r.get("payment_type") != "Internal Transfer":
            continue
        if r.get("base_net_amount") is not None:
            continue   # SQL already handled (one side matched company default)
        issued_amount = flt(r.get("net_amount"))      # = issued_amount for IT
        issued_currency = r.get("currency_code")      # = issued_currency for IT
        base_currency = r.get("base_currency_code")
        if not (issued_amount and issued_currency and base_currency):
            r["base_net_amount"] = 0
            continue
        try:
            rate = get_exchange_rate(
                issued_currency, base_currency, r.get("posting_date"),
            ) or 0
            r["base_net_amount"] = flt(issued_amount * rate, 2)
        except Exception as e:
            frappe.log_error(
                f"PRF Summary cross-currency rate lookup failed for {r['name']}: {e}",
                "Payment Request Form Summary",
            )
            r["base_net_amount"] = 0


def _build_conditions(filters):
    clauses = []
    params = {}

    if filters.get("from_date"):
        clauses.append("AND prf.posting_date >= %(from_date)s")
        params["from_date"] = filters.from_date
    if filters.get("to_date"):
        clauses.append("AND prf.posting_date <= %(to_date)s")
        params["to_date"] = filters.to_date
    if filters.get("company"):
        clauses.append("AND prf.company = %(company)s")
        params["company"] = filters.company
    if filters.get("party_type"):
        clauses.append("AND prf.party_type = %(party_type)s")
        params["party_type"] = filters.party_type
    if filters.get("party"):
        clauses.append("AND prf.party = %(party)s")
        params["party"] = filters.party
    if filters.get("payment_type"):
        clauses.append("AND prf.payment_type = %(payment_type)s")
        params["payment_type"] = filters.payment_type
    if filters.get("workflow_state"):
        clauses.append("AND prf.workflow_state = %(workflow_state)s")
        params["workflow_state"] = filters.workflow_state
    if filters.get("department"):
        clauses.append("AND prf.department = %(department)s")
        params["department"] = filters.department

    return " ".join(clauses), params
