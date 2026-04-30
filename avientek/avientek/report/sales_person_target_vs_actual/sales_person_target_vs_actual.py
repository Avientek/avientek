# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt

"""Sales Person Target vs Actual.

Tree view: top-level row per Sales Person (totals), expandable to 12
month-level child rows.

Targets: from submitted Sales Person Target / Detail rows for the
filter Fiscal Year. Aggregated per (sales_person) for the parent row
and per (sales_person, month) for child rows.

Booking actual: Sales Order.grand_total via Sales Team allocated %,
converted to the reporting currency.

Billing actual: Sales Invoice.grand_total same way.

Margin actual: SI base_grand_total minus cost-of-goods. The cost
query unions two paths so it works for both Avientek's flow (SI from
DN, update_stock=0, SLE on the DN) and direct/POS SIs (SLE on the
SI itself):

    cost(SI) = SUM(ABS(sle.stock_value_difference))
               WHERE sle.actual_qty < 0
                 AND (
                       (sle.voucher_type = 'Sales Invoice'
                        AND sle.voucher_no = SI.name)
                     OR
                       (sle.voucher_type = 'Delivery Note'
                        AND sle.voucher_no IN
                          (SELECT delivery_note FROM `tabSales Invoice Item`
                           WHERE parent = SI.name
                             AND delivery_note IS NOT NULL
                             AND delivery_note != ''))
                     )

For service / non-stock items there's no SLE → cost contribution is
0, so margin = billing for those line items. That's correct.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate


_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_MONTH_BY_NUM = {i + 1: name for i, name in enumerate(_MONTHS)}


def execute(filters: dict | None = None):
    filters = frappe._dict(filters or {})
    if not filters.get("fiscal_year"):
        frappe.throw(_("Fiscal Year is required."))

    fy_start, fy_end = _fiscal_year_dates(filters.fiscal_year)
    target_currency = filters.get("currency") or "USD"

    # All buckets keyed by (sp, month); month=None means parent-level total.
    targets = _targets(filters)                               # {(sp, month): {bk, bl, mg}}
    booking = _booking_actuals(filters, fy_start, fy_end, target_currency)  # {(sp, month): amt}
    billing, margin = _billing_margin_actuals(filters, fy_start, fy_end, target_currency)

    # Set of all SPs with any data
    all_sps = set()
    for d in (targets, booking, billing, margin):
        for (sp, _m) in d:
            all_sps.add(sp)

    rows: list[dict] = []
    for sp in sorted(all_sps):
        rows.append(_build_row(sp, None, targets, booking, billing, margin, target_currency))
        # Add month rows that have any data
        for month in _MONTHS:
            key = (sp, month)
            if any(key in d for d in (targets, booking, billing, margin)):
                rows.append(_build_row(sp, month, targets, booking, billing, margin, target_currency))

    return _columns(target_currency), rows


# ── row builder ───────────────────────────────────────────────────────

def _build_row(sp, month, targets, booking, billing, margin, currency):
    """Build a single result row. month=None → parent (SP total).
    Month rows show only that month's data."""
    if month is None:
        bk_t = sum(v["bk"] for k, v in targets.items() if k[0] == sp)
        bl_t = sum(v["bl"] for k, v in targets.items() if k[0] == sp)
        mg_t = sum(v["mg"] for k, v in targets.items() if k[0] == sp)
        bk_a = sum(v for k, v in booking.items() if k[0] == sp)
        bl_a = sum(v for k, v in billing.items() if k[0] == sp)
        mg_a = sum(v for k, v in margin.items() if k[0] == sp)
        name = sp
        parent = ""
        indent = 0
        period_label = sp
    else:
        t = targets.get((sp, month), {"bk": 0, "bl": 0, "mg": 0})
        bk_t, bl_t, mg_t = t["bk"], t["bl"], t["mg"]
        bk_a = booking.get((sp, month), 0)
        bl_a = billing.get((sp, month), 0)
        mg_a = margin.get((sp, month), 0)
        name = f"{sp}::{month}"
        parent = sp
        indent = 1
        period_label = month

    return {
        "name": name,
        "parent_target": parent,
        "indent": indent,
        "sales_person": sp if month is None else None,
        "period": period_label,
        "currency": currency,
        "target_booking": flt(bk_t),
        "actual_booking": flt(bk_a),
        "booking_variance": flt(bk_a) - flt(bk_t),
        "booking_pct": flt((bk_a / bk_t * 100), 2) if bk_t else 0,
        "target_billing": flt(bl_t),
        "actual_billing": flt(bl_a),
        "billing_variance": flt(bl_a) - flt(bl_t),
        "billing_pct": flt((bl_a / bl_t * 100), 2) if bl_t else 0,
        "target_margin": flt(mg_t),
        "actual_margin": flt(mg_a),
        "margin_variance": flt(mg_a) - flt(mg_t),
        "margin_pct": flt((mg_a / mg_t * 100), 2) if mg_t else 0,
    }


# ── columns ───────────────────────────────────────────────────────────

def _columns(currency):
    return [
        {"label": _("Sales Person / Month"), "fieldname": "period", "fieldtype": "Data", "width": 200},
        {"label": _("Sales Person"), "fieldname": "sales_person", "fieldtype": "Link", "options": "Sales Person", "width": 0, "hidden": 1},
        {"label": _("Target Booking"), "fieldname": "target_booking", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Actual Booking"), "fieldname": "actual_booking", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Booking Variance"), "fieldname": "booking_variance", "fieldtype": "Currency", "options": "currency", "width": 140},
        {"label": _("Booking %"), "fieldname": "booking_pct", "fieldtype": "Percent", "width": 90},
        {"label": _("Target Billing"), "fieldname": "target_billing", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Actual Billing"), "fieldname": "actual_billing", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Billing Variance"), "fieldname": "billing_variance", "fieldtype": "Currency", "options": "currency", "width": 140},
        {"label": _("Billing %"), "fieldname": "billing_pct", "fieldtype": "Percent", "width": 90},
        {"label": _("Target Margin"), "fieldname": "target_margin", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Actual Margin"), "fieldname": "actual_margin", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Margin Variance"), "fieldname": "margin_variance", "fieldtype": "Currency", "options": "currency", "width": 130},
        {"label": _("Margin %"), "fieldname": "margin_pct", "fieldtype": "Percent", "width": 90},
        {"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 80},
    ]


# ── data sources ──────────────────────────────────────────────────────

def _fiscal_year_dates(fiscal_year):
    row = frappe.db.get_value(
        "Fiscal Year", fiscal_year,
        ["year_start_date", "year_end_date"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Fiscal Year {0} not found.").format(fiscal_year))
    return row.year_start_date, row.year_end_date


def _targets(filters):
    """Per-month targets per SP: {(sp, month): {bk, bl, mg}}."""
    where = ["spt.docstatus = 1", "spt.fiscal_year = %s"]
    args = [filters.fiscal_year]
    if filters.get("sales_person"):
        where.append("spt.sales_person = %s")
        args.append(filters.sales_person)
    if filters.get("company"):
        where.append("(spt.company = %s OR spt.company IS NULL OR spt.company = '')")
        args.append(filters.company)

    rows = frappe.db.sql(
        f"""SELECT spt.sales_person AS sp,
                   spd.month,
                   SUM(spd.target_booking) AS bk,
                   SUM(spd.target_billing) AS bl,
                   SUM(spd.target_margin)  AS mg
            FROM `tabSales Person Target` spt
            INNER JOIN `tabSales Person Target Detail` spd ON spd.parent = spt.name
            WHERE {' AND '.join(where)}
            GROUP BY spt.sales_person, spd.month""",
        args, as_dict=True,
    )
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        if not r.month:
            continue
        out[(r.sp, r.month)] = {
            "bk": flt(r.bk), "bl": flt(r.bl), "mg": flt(r.mg),
        }
    return out


def _booking_actuals(filters, fy_start, fy_end, target_currency):
    """{(sp, month): amount} from Sales Order via Sales Team allocation."""
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
        f"""SELECT st.sales_person AS sp,
                   MONTH(so.transaction_date) AS month_num,
                   so.currency AS doc_currency,
                   so.transaction_date AS posting_date,
                   so.grand_total,
                   st.allocated_percentage
            FROM `tabSales Order` so
            INNER JOIN `tabSales Team` st ON st.parent = so.name
            WHERE {' AND '.join(where)}""",
        args, as_dict=True,
    )
    return _aggregate_by_sp_month(rows, target_currency)


def _billing_margin_actuals(filters, fy_start, fy_end, target_currency):
    """Returns ({(sp, month): billing}, {(sp, month): margin}).

    Two-pass query for performance — the correlated subquery version
    timed out on production-clone data because the inner DN-list IN
    expression re-evaluated per outer row.

    Pass 1 (one query): list SIs in scope with their grand_total,
            base_grand_total, currency, posting_date, and Sales Team
            allocation rows.
    Pass 2 (one query): cost via SLE where voucher_type='Sales Invoice'
            and voucher_no IN si_names.
    Pass 3 (one query): for SI Item rows that point to a DN, get the
            cost via SLE where voucher_type='Delivery Note' and
            voucher_no IN those DNs.
    Combine in Python.
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
        f"""SELECT
                si.name AS si_name,
                si.company AS si_company,
                st.sales_person AS sp,
                MONTH(si.posting_date) AS month_num,
                si.currency AS doc_currency,
                si.posting_date AS posting_date,
                si.grand_total,
                si.base_grand_total,
                st.allocated_percentage
            FROM `tabSales Invoice` si
            INNER JOIN `tabSales Team` st ON st.parent = si.name
            WHERE {' AND '.join(where)}""",
        args, as_dict=True,
    )

    billing = _aggregate_by_sp_month(rows, target_currency)

    # Compute cost-of-goods per SI in two passes.
    si_names = list({r.si_name for r in rows})
    si_cost = _si_cost_map(si_names) if si_names else {}

    # Margin: convert (base_grand_total − cost) from company currency
    # to target currency, allocate by Sales Team %.
    fx_cache: dict[Any, float] = {}
    co_cur_cache: dict[str, str] = {}
    margin: dict[tuple[str, str], float] = defaultdict(float)
    for r in rows:
        pct = flt(r.allocated_percentage) / 100.0 if r.allocated_percentage else 1.0
        cost = si_cost.get(r.si_name, 0.0)
        margin_company = flt(r.base_grand_total) - cost
        company = r.si_company
        if company not in co_cur_cache:
            co_cur_cache[company] = frappe.get_cached_value(
                "Company", company, "default_currency"
            ) or target_currency
        from_cur = co_cur_cache[company]
        rate = _fx(from_cur, target_currency, r.posting_date, fx_cache)
        month = _MONTH_BY_NUM.get(int(r.month_num)) if r.month_num else None
        if not month:
            continue
        margin[(r.sp, month)] += margin_company * rate * pct
    return billing, dict(margin)


def _si_cost_map(si_names):
    """Return {si_name: cost_of_goods_in_company_currency}.

    Cost = SUM of |stock_value_difference| from Stock Ledger Entries
    that came from either:
      (a) the Sales Invoice itself (update_stock=1 case), or
      (b) any Delivery Note linked from a Sales Invoice Item (Avientek
          DN→SI flow with update_stock=0).

    Each SI gets at most one path's costs in practice (SI rows with
    update_stock=1 have SLE on SI; rows from DN have SLE on DN, not on
    the SI). If both happen we sum them — over-counting risk is small
    on the Avientek setup.
    """
    cost: dict[str, float] = defaultdict(float)
    if not si_names:
        return cost

    # Phase A: SLE on the SI directly (typical for POS / direct SIs)
    ph = ", ".join(["%s"] * len(si_names))
    rows_a = frappe.db.sql(
        f"""SELECT voucher_no AS si_name,
                   SUM(ABS(stock_value_difference)) AS cost
            FROM `tabStock Ledger Entry`
            WHERE voucher_type = 'Sales Invoice'
              AND actual_qty < 0
              AND voucher_no IN ({ph})
            GROUP BY voucher_no""",
        si_names, as_dict=True,
    )
    for r in rows_a:
        cost[r.si_name] += flt(r.cost)

    # Phase B: SI Item rows that reference a DN — sum SLE on those DNs.
    # Get unique (si, dn) pairs first so we don't double-count when the
    # same DN appears on multiple SI item rows.
    si_dn = frappe.db.sql(
        f"""SELECT DISTINCT parent AS si_name, delivery_note AS dn
            FROM `tabSales Invoice Item`
            WHERE delivery_note IS NOT NULL AND delivery_note != ''
              AND parent IN ({ph})""",
        si_names, as_dict=True,
    )
    si_to_dns: dict[str, set[str]] = defaultdict(set)
    all_dns: set[str] = set()
    for r in si_dn:
        si_to_dns[r.si_name].add(r.dn)
        all_dns.add(r.dn)

    if all_dns:
        dn_list = list(all_dns)
        ph2 = ", ".join(["%s"] * len(dn_list))
        dn_cost_rows = frappe.db.sql(
            f"""SELECT voucher_no AS dn,
                       SUM(ABS(stock_value_difference)) AS cost
                FROM `tabStock Ledger Entry`
                WHERE voucher_type = 'Delivery Note'
                  AND actual_qty < 0
                  AND voucher_no IN ({ph2})
                GROUP BY voucher_no""",
            dn_list, as_dict=True,
        )
        dn_cost = {r.dn: flt(r.cost) for r in dn_cost_rows}
        for si_name, dns in si_to_dns.items():
            cost[si_name] += sum(dn_cost.get(dn, 0) for dn in dns)

    return dict(cost)


def _aggregate_by_sp_month(rows, target_currency):
    fx_cache: dict[Any, float] = {}
    out: dict[tuple[str, str], float] = defaultdict(float)
    for r in rows:
        pct = flt(r.allocated_percentage) / 100.0 if r.allocated_percentage else 1.0
        rate = _fx(r.doc_currency, target_currency, r.posting_date, fx_cache)
        month = _MONTH_BY_NUM.get(int(r.month_num)) if r.month_num else None
        if not month:
            continue
        out[(r.sp, month)] += flt(r.grand_total) * rate * pct
    return dict(out)


def _fx(from_currency, to_currency, posting_date, cache):
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
