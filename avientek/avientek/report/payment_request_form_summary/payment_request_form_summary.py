# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Payment Request Form Summary — consolidated view of every PRF
# with a single Net Amount + Currency pair regardless of payment_type.
# Internal Transfer rows show the issued_amount / issued_currency;
# Pay / Advance Pay rows show the total_outstanding_amount / currency.

import frappe
from frappe import _


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return _columns(), _data(filters)


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
        {"label": _("Net Amount"), "fieldname": "net_amount", "fieldtype": "Currency",
         "options": "currency_code", "width": 140},
        {"label": _("Currency"), "fieldname": "currency_code", "fieldtype": "Link",
         "options": "Currency", "width": 80},
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link",
         "options": "Company", "width": 180},
        {"label": _("Department"), "fieldname": "department", "fieldtype": "Link",
         "options": "Department", "width": 140},
        {"label": _("Payment Mode"), "fieldname": "payment_mode", "fieldtype": "Link",
         "options": "Mode of Payment", "width": 130},
        {"label": _("Issued Bank"), "fieldname": "issued_bank", "fieldtype": "Link",
         "options": "Bank Account", "width": 160},
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
            CASE
                WHEN prf.payment_type = 'Internal Transfer' THEN prf.issued_amount
                ELSE prf.total_outstanding_amount
            END AS net_amount,
            CASE
                WHEN prf.payment_type = 'Internal Transfer' THEN prf.issued_currency
                ELSE prf.currency
            END AS currency_code,
            prf.company,
            prf.department,
            prf.payment_mode,
            prf.issued_bank,
            prf.owner
        FROM `tabPayment Request Form` prf
        WHERE prf.docstatus < 2
            {where}
        ORDER BY prf.posting_date DESC, prf.name DESC
    """.format(where=where)
    return frappe.db.sql(sql, params, as_dict=True)


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
