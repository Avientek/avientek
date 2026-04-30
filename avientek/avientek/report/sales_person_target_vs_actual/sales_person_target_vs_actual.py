# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt

"""Sales Person Target vs Actual.

One row per Sales Person showing:
  - Total Target Booking / Billing / Margin (from submitted Sales
    Person Target for the filter Fiscal Year)
  - Total Actual Booking / Billing / Margin (from Sales Order /
    Sales Invoice / SLE-derived gross profit)
  - Variance and % Achievement for each pair

Allocation: when an SO/SI has multiple Sales Team rows, each row's
allocated_percentage is applied so an SP's actuals only count their
share of the deal.

Currency: targets store their own currency (default USD). Actuals are
converted to the target's currency via Currency Exchange spot rate at
the SO/SI posting date. The filter also exposes a `currency` override
so reports can be re-run in any reporting currency.

v1 scope: Sales-Person totals only (no per-month / per-brand
breakdown). Group-by extensions come later — the data is in
`tabSales Person Target Detail` already, but the UX of a tree view
adds complexity I'd rather defer.
"""

from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters: dict | None = None):
    filters = frappe._dict(filters or {})
    if not filters.get("fiscal_year"):
        frappe.throw(_("Fiscal Year is required."))

    fy_start, fy_end = _fiscal_year_dates(filters.fiscal_year)
    target_currency = filters.get("currency") or "USD"

    targets_by_sp = _targets_by_sp(filters)
    booking_by_sp = _booking_actuals(filters, fy_start, fy_end, target_currency)
    billing_by_sp, margin_by_sp = _billing_margin_actuals(filters, fy_start, fy_end, target_currency)

    sps = sorted(set(targets_by_sp) | set(booking_by_sp) | set(billing_by_sp))
    rows = []
    for sp in sps:
        t = targets_by_sp.get(sp, {"booking": 0, "billing": 0, "margin": 0, "include_descendants": 0})
        ab = flt(booking_by_sp.get(sp, 0))
        ai = flt(billing_by_sp.get(sp, 0))
        am = flt(margin_by_sp.get(sp, 0))
        rows.append({
            "sales_person": sp,
            "currency": target_currency,
            "target_booking": flt(t["booking"]),
            "actual_booking": ab,
            "booking_variance": ab - flt(t["booking"]),
            "booking_pct": flt((ab / t["booking"] * 100), 2) if t["booking"] else 0,
            "target_billing": flt(t["billing"]),
            "actual_billing": ai,
            "billing_variance": ai - flt(t["billing"]),
            "billing_pct": flt((ai / t["billing"] * 100), 2) if t["billing"] else 0,
            "target_margin": flt(t["margin"]),
            "actual_margin": am,
            "margin_variance": am - flt(t["margin"]),
            "margin_pct": flt((am / t["margin"] * 100), 2) if t["margin"] else 0,
        })

    return _columns(target_currency), rows


# ── helpers ───────────────────────────────────────────────────────────

def _columns(currency):
    return [
        {"label": _("Sales Person"), "fieldname": "sales_person", "fieldtype": "Link", "options": "Sales Person", "width": 180},
        {"label": _("Target Booking"), "fieldname": "target_booking", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Actual Booking"), "fieldname": "actual_booking", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Booking Variance"), "fieldname": "booking_variance", "fieldtype": "Currency", "options": "currency", "width": 140},
        {"label": _("Booking %"), "fieldname": "booking_pct", "fieldtype": "Percent", "width": 100},
        {"label": _("Target Billing"), "fieldname": "target_billing", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Actual Billing"), "fieldname": "actual_billing", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Billing Variance"), "fieldname": "billing_variance", "fieldtype": "Currency", "options": "currency", "width": 140},
        {"label": _("Billing %"), "fieldname": "billing_pct", "fieldtype": "Percent", "width": 100},
        {"label": _("Target Margin"), "fieldname": "target_margin", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Actual Margin"), "fieldname": "actual_margin", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Margin Variance"), "fieldname": "margin_variance", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Margin %"), "fieldname": "margin_pct", "fieldtype": "Percent", "width": 100},
        {"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 80},
    ]


def _fiscal_year_dates(fiscal_year):
    row = frappe.db.get_value(
        "Fiscal Year", fiscal_year,
        ["year_start_date", "year_end_date"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Fiscal Year {0} not found.").format(fiscal_year))
    return row.year_start_date, row.year_end_date


def _targets_by_sp(filters):
    """Sum total_target_* per sales_person from submitted Sales Person Target
    records matching the fiscal year (and optional sales_person / company).
    Returns {sp: {booking, billing, margin, include_descendants}}.
    """
    where = ["docstatus = 1", "fiscal_year = %s"]
    args = [filters.fiscal_year]
    if filters.get("sales_person"):
        where.append("sales_person = %s")
        args.append(filters.sales_person)
    if filters.get("company"):
        where.append("(company = %s OR company IS NULL OR company = '')")
        args.append(filters.company)

    rows = frappe.db.sql(
        f"""SELECT sales_person,
                   SUM(total_target_booking) AS booking,
                   SUM(total_target_billing) AS billing,
                   SUM(total_target_margin)  AS margin
            FROM `tabSales Person Target`
            WHERE {' AND '.join(where)}
            GROUP BY sales_person""",
        args, as_dict=True,
    )
    return {
        r.sales_person: {
            "booking": flt(r.booking),
            "billing": flt(r.billing),
            "margin": flt(r.margin),
        }
        for r in rows
    }


def _booking_actuals(filters, fy_start, fy_end, target_currency):
    """Sum Sales Order grand_total per Sales Person via Sales Team
    allocated_percentage. Converted from SO transaction currency to
    target_currency at posting date."""
    where = [
        "so.docstatus = 1",
        "so.transaction_date BETWEEN %s AND %s",
        "st.parenttype = 'Sales Order'",
        "st.sales_person IS NOT NULL",
        "st.sales_person != ''",
    ]
    args = [fy_start, fy_end]
    if filters.get("company"):
        where.append("so.company = %s")
        args.append(filters.company)
    if filters.get("sales_person"):
        where.append("st.sales_person = %s")
        args.append(filters.sales_person)

    rows = frappe.db.sql(
        f"""SELECT st.sales_person,
                   so.currency AS so_currency,
                   so.transaction_date AS posting_date,
                   so.grand_total,
                   so.base_grand_total,
                   st.allocated_percentage
            FROM `tabSales Order` so
            INNER JOIN `tabSales Team` st ON st.parent = so.name
            WHERE {' AND '.join(where)}""",
        args, as_dict=True,
    )
    return _aggregate_by_sp(rows, target_currency)


def _billing_margin_actuals(filters, fy_start, fy_end, target_currency):
    """Sum Sales Invoice grand_total + computed margin per Sales Person.
    Margin per SI = base_grand_total - SUM(|SLE.stock_value_difference|)
    for outgoing rows. Service items / non-stock items contribute their
    full base_amount to margin (no SLE → buying = 0).
    """
    where = [
        "si.docstatus = 1",
        "si.posting_date BETWEEN %s AND %s",
        "st.parenttype = 'Sales Invoice'",
        "st.sales_person IS NOT NULL",
        "st.sales_person != ''",
    ]
    args = [fy_start, fy_end]
    if filters.get("company"):
        where.append("si.company = %s")
        args.append(filters.company)
    if filters.get("sales_person"):
        where.append("st.sales_person = %s")
        args.append(filters.sales_person)

    rows = frappe.db.sql(
        f"""SELECT si.name AS si_name,
                   st.sales_person,
                   si.currency AS so_currency,
                   si.posting_date AS posting_date,
                   si.grand_total,
                   si.base_grand_total,
                   st.allocated_percentage,
                   (SELECT COALESCE(SUM(ABS(sle.stock_value_difference)), 0)
                      FROM `tabStock Ledger Entry` sle
                      WHERE sle.voucher_type = 'Sales Invoice'
                        AND sle.voucher_no = si.name
                        AND sle.actual_qty < 0) AS buying_company_currency
            FROM `tabSales Invoice` si
            INNER JOIN `tabSales Team` st ON st.parent = si.name
            WHERE {' AND '.join(where)}""",
        args, as_dict=True,
    )

    # Booking-style billing aggregation
    billing_by_sp = _aggregate_by_sp(rows, target_currency)

    # Margin: base_grand_total - buying (both in company currency), then
    # convert to target_currency. Allocated by SP percentage.
    fx_cache: dict[Any, float] = {}
    margin_by_sp: dict[str, float] = defaultdict(float)
    for r in rows:
        # base_* fields are in company currency. To get target currency,
        # we need company_currency → target_currency rate. We don't carry
        # company currency here; use SO/SI's existing conversion_rate
        # backward: target_value = base_value / (target_currency / company_currency).
        # Simpler: convert base_value via stored exchange table.
        pct = flt(r.allocated_percentage) / 100.0 if r.allocated_percentage else 1.0
        margin_company = flt(r.base_grand_total) - flt(r.buying_company_currency)
        # Pull company currency once and convert.
        company = frappe.db.get_value("Sales Invoice", r.si_name, "company")
        company_currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
        rate = _fx(company_currency or target_currency, target_currency, r.posting_date, fx_cache)
        margin_by_sp[r.sales_person] += margin_company * rate * pct

    return billing_by_sp, dict(margin_by_sp)


def _aggregate_by_sp(rows, target_currency):
    """Sum per-Sales-Person from rows that carry so_currency, posting_date,
    grand_total (transaction currency), allocated_percentage."""
    fx_cache: dict[Any, float] = {}
    out: dict[str, float] = defaultdict(float)
    for r in rows:
        pct = flt(r.allocated_percentage) / 100.0 if r.allocated_percentage else 1.0
        rate = _fx(r.so_currency, target_currency, r.posting_date, fx_cache)
        out[r.sales_person] += flt(r.grand_total) * rate * pct
    return dict(out)


def _fx(from_currency, to_currency, posting_date, cache):
    """Exchange rate from_currency → to_currency at posting_date.
    Cached per (from, to, date). Falls back to 1 if same currency or no
    rate available.
    """
    if not from_currency or not to_currency or from_currency == to_currency:
        return 1.0
    key = (from_currency, to_currency, getdate(posting_date))
    if key in cache:
        return cache[key]
    try:
        from erpnext.setup.utils import get_exchange_rate
        rate = flt(get_exchange_rate(from_currency, to_currency, posting_date)) or 1.0
    except Exception:
        rate = 1.0
    cache[key] = rate
    return rate
