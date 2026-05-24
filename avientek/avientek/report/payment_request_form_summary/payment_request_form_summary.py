# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Payment Request Form Summary — consolidated view of every PRF.
#
# Column structure (Jithin's 2026-05-23 template + same-day clarification):
#   PRF Amount                 — for IT: RECEIVING side (destination
#                                bank's deposit amount); for non-IT:
#                                sum of child outstanding amounts.
#   PRF-Amount Company Currency — base/company-currency equivalent
#                                (always shown, no opt-in toggle)
#   Amount                     — for IT: ISSUED/SOURCE side (the
#                                other leg of the transfer); for
#                                non-IT: blank.
#   PRF-Currency               — for IT: receiving_currency; for
#                                non-IT: document currency code.
#   Issued Currency            — for IT: issued_currency (source of
#                                the 'Amount' column); blank otherwise.
#
# Rationale (Jithin's WhatsApp 2026-05-23 PM): the actual cash that
# arrives in the bank account is what finance reviews — that's the
# receiving side. The issued side is supplementary (shown in the
# Amount + Issued Currency pair for cross-currency clarity).
#
# IT base_net_amount fallback:
#   1. receiving_currency = company_default → receiving_amount (direct)
#   2. else → receiving_amount × FX(receiving_currency → company_default)
#      via erpnext.setup.utils.get_exchange_rate (Python post-pass).
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
        {"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 120},
        {"label": _("Status"), "fieldname": "workflow_state", "fieldtype": "Data", "width": 140},
        {"label": _("Payment Type"), "fieldname": "payment_type", "fieldtype": "Data", "width": 130},
        {"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Link",
         "options": "DocType", "width": 100},
        {"label": _("Party"), "fieldname": "party", "fieldtype": "Dynamic Link",
         "options": "party_type", "width": 160},
        {"label": _("Party Name"), "fieldname": "party_name", "fieldtype": "Data", "width": 400},
        # Renamed columns per Jithin 2026-05-23 template:
        {"label": _("PRF Amount"), "fieldname": "net_amount", "fieldtype": "Currency",
         "options": "currency_code", "width": 140},
        {"label": _("PRF-Amount Company Currency"), "fieldname": "base_net_amount",
         "fieldtype": "Currency", "options": "base_currency_code", "width": 250},
        # Jithin 2026-05-23 follow-up: for IT rows, PRF Amount must be
        # the RECEIVING side (destination = what arrives in the bank).
        # The 'Amount' column now shows the ISSUED side (source =
        # what was sent). Paired "Issued Currency" column makes the
        # source leg's currency explicit for cross-currency transfers.
        {"label": _("Amount"), "fieldname": "other_amount", "fieldtype": "Currency",
         "options": "other_currency", "width": 140},
        {"label": _("PRF-Currency"), "fieldname": "currency_code", "fieldtype": "Link",
         "options": "Currency", "width": 130},
        {"label": _("Issued Currency"), "fieldname": "other_currency",
         "fieldtype": "Link", "options": "Currency", "width": 120},
        {"label": _("Base Currency"), "fieldname": "base_currency_code",
         "fieldtype": "Link", "options": "Currency", "width": 90},
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link",
         "options": "Company", "width": 300},
        {"label": _("Department"), "fieldname": "department", "fieldtype": "Link",
         "options": "Department", "width": 140},
        {"label": _("Payment Mode"), "fieldname": "payment_mode", "fieldtype": "Link",
         "options": "Mode of Payment", "width": 130},
        {"label": _("Issued Bank"), "fieldname": "issued_bank", "fieldtype": "Link",
         "options": "Bank Account", "width": 160},
        {"label": _("Beneficiary Name"), "fieldname": "beneficiary_name",
         "fieldtype": "Data", "width": 180},
        {"label": _("Created By"), "fieldname": "owner", "fieldtype": "Link",
         "options": "User", "width": 250},
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

            /* PRF Amount — Jithin 2026-05-23: for IT this is the
               RECEIVING side (destination bank's deposit amount); for
               non-IT it sums the child outstanding amounts. */
            CASE
                WHEN prf.payment_type = 'Internal Transfer' THEN prf.receiving_amount
                ELSE IFNULL((
                    SELECT SUM(pr.outstanding_amount)
                    FROM `tabPayment Request Reference` pr
                    WHERE pr.parent = prf.name
                ), 0)
            END AS net_amount,

            /* PRF-Currency — for IT, the RECEIVING currency; for non-IT
               pick MAX(child.currency) for single-currency PRFs. */
            CASE
                WHEN prf.payment_type = 'Internal Transfer' THEN prf.receiving_currency
                ELSE IFNULL((
                    SELECT MAX(pr.currency)
                    FROM `tabPayment Request Reference` pr
                    WHERE pr.parent = prf.name
                      AND pr.currency IS NOT NULL
                      AND pr.currency != ''
                ), prf.currency)
            END AS currency_code,

            /* Amount + Issued Currency — for IT, the SOURCE/ISSUED side
               (the other leg of the transfer). NULL for non-IT (no source
               leg distinct from the invoice rows). */
            CASE
                WHEN prf.payment_type = 'Internal Transfer'
                    THEN prf.issued_amount
                ELSE NULL
            END AS other_amount,
            CASE
                WHEN prf.payment_type = 'Internal Transfer'
                    THEN prf.issued_currency
                ELSE NULL
            END AS other_currency,

            /* PRF-Amount Company Currency — base/company-currency value.
               Now sourced from the RECEIVING side (matches the new PRF
               Amount semantics):
                 IT ladder: receiving_currency matches base → receiving_amount;
                            else NULL (filled in Python via FX lookup on
                            receiving_amount). */
            CASE
                WHEN prf.payment_type = 'Internal Transfer' THEN
                    CASE
                        WHEN prf.receiving_currency =
                            (SELECT default_currency FROM `tabCompany` WHERE name = prf.company)
                            THEN prf.receiving_amount
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
    """Post-SQL: for Internal Transfer rows where the receiving currency
    doesn't match the company default, compute the base equivalent via
    get_exchange_rate(receiving_currency, base, date).

    Jithin 2026-05-23: PRF Amount = receiving side, so the company-
    currency conversion is from the receiving side. SQL already
    populated base_net_amount when receiving_currency = company base
    (no conversion needed). Everything else lands here.
    """
    for r in rows:
        if r.get("payment_type") != "Internal Transfer":
            continue
        if r.get("base_net_amount") is not None:
            continue   # SQL handled it (receiving matched company base)
        receiving_amount = flt(r.get("net_amount"))   # PRF Amount = receiving
        receiving_currency = r.get("currency_code")   # PRF-Currency = receiving
        base_currency = r.get("base_currency_code")
        if not (receiving_amount and receiving_currency and base_currency):
            r["base_net_amount"] = 0
            continue
        try:
            rate = get_exchange_rate(
                receiving_currency, base_currency, r.get("posting_date"),
            ) or 0
            r["base_net_amount"] = flt(receiving_amount * rate, 2)
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
