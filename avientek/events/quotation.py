import frappe
from frappe import _
from frappe.utils import flt, cint
from frappe.model.workflow import apply_workflow
import json
from decimal import Decimal, ROUND_HALF_UP

# Decimal counterpart of _ZERO_TOL (see the "Near-zero denominators" note
# further down). Same rule, same reason: half a fils is not money, and a
# residue that small must never reach a percentage divisor.
_DEC_ZERO_TOL = Decimal("0.005")


@frappe.whitelist()
def get_customer_outstanding(customer, company):
    """Get total outstanding from Sales Invoices for a customer (bypasses doctype permission)."""
    outstanding = frappe.db.sql("""
        SELECT IFNULL(SUM(outstanding_amount), 0) as total
        FROM `tabSales Invoice`
        WHERE customer=%s AND company=%s AND docstatus=1
    """, (customer, company), as_dict=True)
    return flt(outstanding[0].total) if outstanding else 0


@frappe.whitelist()
def apply_discount(doc, discount_amount):
    quotation = frappe.parse_json(doc)

    discount = Decimal(str(discount_amount or 0))
    if discount < 0:
        frappe.throw("Please enter a valid discount amount")

    items = quotation.get("items", []) or []

    if not items:
        frappe.throw("No items available to apply discount")

    new_items = items

    # Calculate total selling value (BEFORE discount)
    total_selling = Decimal("0.0")
    for i in new_items:
        selling = Decimal(str(
            i.get("custom_selling_price")
            or i.get("amount")
            or 0
        ))
        total_selling += selling

    if total_selling <= 0:
        frappe.throw("Invalid selling amount")

    q = lambda x: float(x.quantize(Decimal("1.0000"), rounding=ROUND_HALF_UP))

    updated_items = []
    total_new_selling = Decimal("0.0")

    for i in new_items:
        name = i.get("name")
        qty = Decimal(str(i.get("qty") or 0))

        selling = Decimal(str(
            i.get("custom_selling_price")
            or i.get("amount")
            or 0
        ))

        # Proportional discount
        share = selling / total_selling
        item_discount = discount * share

        new_selling = selling - item_discount
        # Covers both a negative overshoot and a sub-fils positive residue;
        # the latter is truthy and would otherwise blow up new_margin_pct.
        if new_selling < _DEC_ZERO_TOL:
            new_selling = Decimal("0.0")

        new_rate = new_selling / qty if qty else Decimal("0.0")
        # Margin recalculation
        cost_rate = Decimal(str((i.get("custom_cogs") or 0)))
        selling_rate = new_selling

        new_margin_val = (selling_rate - cost_rate)
        if new_margin_val < 0:
            new_margin_val = Decimal("0.0")

        new_margin_pct = (
            ((selling_rate - cost_rate) / selling_rate) * 100
            if abs(selling_rate) >= _DEC_ZERO_TOL else Decimal("0.0")
        )

        updated_items.append({
            "name": name,
            "allocated_discount": q(item_discount),
            "custom_special_rate": q(new_rate),
            "custom_selling_price": q(new_selling),
            "custom_discount_amount_value": (
                (item_discount / qty).quantize(Decimal("1.0000"), rounding=ROUND_HALF_UP)
                if qty else Decimal("0.0")
            ),

            "custom_discount_amount_qty": q(item_discount),
            "custom_margin_value": q(new_margin_val),
            "custom_margin_": q(new_margin_pct),
        })

        total_new_selling += new_selling

    parent_discount_pct = (
        q((discount / total_selling) * 100)
        if abs(total_selling) >= _DEC_ZERO_TOL else 0.0
    )

    exchange_rate = Decimal(str(quotation.get("conversion_rate") or 1))

    return {
        "custom_discount_amount_value": q(discount),
        "custom_discount_": parent_discount_pct,
        "items": updated_items,
        "total": q(total_new_selling),
        "base_total": q(total_new_selling * exchange_rate),
    }

@frappe.whitelist()
def get_item_all_details(item_code, customer, price_list, company=None):
    return {
        "history": get_last_5_transactions(item_code, customer),
        "stock": get_company_stock(item_code, company),
        "shipment_margin": get_shipment_and_margin(item_code, price_list, company)
    }

def get_last_5_transactions(item_code, customer):
    result = []

    # -----------------------
    # 1️⃣ SALES INVOICE
    # -----------------------
    invoices = frappe.db.sql("""
        SELECT si.name, sii.qty, sii.rate, si.posting_date AS date
        FROM `tabSales Invoice` si
        JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
        WHERE si.customer=%s
          AND sii.item_code=%s
          AND si.docstatus=1
        ORDER BY si.posting_date DESC
        LIMIT 5
    """, (customer, item_code), as_dict=True)

    for r in invoices:
        if len(result) >= 5:
            return result
        result.append({
            "doctype": "Sales Invoice",
            "name": r.name,
            "qty": r.qty,
            "rate": r.rate,
            "date": r.date
        })

    # -----------------------
    # 2️⃣ SALES ORDER (not invoiced)
    # -----------------------
    orders = frappe.db.sql("""
        SELECT so.name, soi.qty, soi.rate, so.transaction_date AS date
        FROM `tabSales Order` so
        JOIN `tabSales Order Item` soi ON soi.parent = so.name
        WHERE so.customer = %s
        AND soi.item_code = %s
        AND so.docstatus = 1
        AND so.status IN ("To Deliver and Bill", "To Deliver", "To Bill", "Completed", "Closed")
        AND NOT EXISTS (
            SELECT 1 FROM `tabSales Invoice Item` sii
            WHERE sii.sales_order = so.name
        )
        ORDER BY so.transaction_date DESC
        LIMIT 5
    """, (customer, item_code), as_dict=True)


    for r in orders:
        if len(result) >= 5:
            return result
        result.append({
            "doctype": "Sales Order",
            "name": r.name,
            "qty": r.qty,
            "rate": r.rate,
            "date": r.date
        })

    # -----------------------
    # 3️⃣ QUOTATION (not ordered)
    # -----------------------
    quotations = frappe.db.sql("""
        SELECT q.name, qi.qty, qi.rate, q.transaction_date AS date
        FROM `tabQuotation` q
        JOIN `tabQuotation Item` qi ON qi.parent = q.name
        WHERE q.party_name=%s
          AND qi.item_code=%s
          AND q.docstatus=1
          AND NOT EXISTS (
              SELECT 1 FROM `tabSales Order Item` soi
              WHERE soi.prevdoc_docname = q.name
          )
        ORDER BY q.transaction_date DESC
        LIMIT 5
    """, (customer, item_code), as_dict=True)

    for r in quotations:
        if len(result) >= 5:
            return result
        result.append({
            "doctype": "Quotation",
            "name": r.name,
            "qty": r.qty,
            "rate": r.rate,
            "date": r.date
        })

    return result
@frappe.whitelist()
def get_company_stock(item_code, company=None):
    stock = []

    # Quotation always has a company set before items are added, so scope
    # the warehouse/bin lookup to it instead of looping every company.
    companies = [company] if company else frappe.get_all("Company", pluck="name")

    for c in companies:
        # Venkatesh/Rahul 2026-06-11 ERP-TKT-29: RMA / Demo / Service /
        # Repair warehouses (21 of them on prod as of 2026-06-11) carry
        # inventory that's NOT available for sale — replacement units,
        # demo loans, FOC stock. Avientek's convention is to tag those
        # with `Warehouse.warehouse_type = "Freezed Items"`. Excluding
        # them here makes the Quote line-item stock indicator reflect
        # what the sales rep can actually quote against.
        #
        # The `IS NULL OR != 'Freezed Items'` clause is deliberate —
        # `["!=", "Freezed Items"]` via Frappe's filter dict would
        # SQL-translate to `<> 'Freezed Items'` which excludes NULL
        # rows too (NULL != X is NULL in SQL). We want NULL-typed
        # warehouses INCLUDED (they're regular inventory warehouses
        # the user just hasn't tagged with a warehouse_type).
        warehouses = frappe.db.sql_list(
            """
            SELECT name FROM `tabWarehouse`
            WHERE company = %s
              AND is_group = 0
              AND (warehouse_type IS NULL OR warehouse_type != 'Freezed Items')
            """,
            (c,),
        )

        if not warehouses:
            continue

        bin_data = frappe.db.sql("""
            SELECT
                SUM(actual_qty) AS actual_qty,
                SUM(reserved_qty) AS reserved_qty,
                SUM(projected_qty) AS projected_qty
            FROM `tabBin`
            WHERE item_code = %s
              AND warehouse IN %s
        """, (item_code, tuple(warehouses)), as_dict=True)[0]

        actual = flt(bin_data.actual_qty)
        reserved = flt(bin_data.reserved_qty)
        projected = flt(bin_data.projected_qty)
        free_stock = max(actual - reserved, 0)

        # 🚨 IMPORTANT FILTER
        if actual == 0 and free_stock == 0 and projected == 0:
            continue

        stock.append({
            "company": c,
            "actual_stock": actual,
            "free_stock": free_stock,
            "projected_stock": projected
        })

    return stock

@frappe.whitelist()
def get_shipment_and_margin(item_code, price_list, company=None):
    if not item_code or not price_list:
        return {}

    fields = [
        "custom_shipping__air_",
        "custom_shipping__sea_",
        "custom_min_margin_",
        "custom_markup_",
    ]

    data = None

    # Try with company filter first (company-specific Item Price)
    if company:
        data = frappe.db.get_value(
            "Item Price",
            {"item_code": item_code, "price_list": price_list, "custom_company": company},
            fields,
            as_dict=True,
        )

    # Fallback: without company filter
    if not data:
        data = frappe.db.get_value(
            "Item Price",
            {"item_code": item_code, "price_list": price_list},
            fields,
            as_dict=True,
        )

    if not data:
        return {}

    return {
        "ship_air": data.custom_shipping__air_ or 0,
        "ship_sea": data.custom_shipping__sea_ or 0,
        "std_margin": data.custom_min_margin_ or 0,
        "markup": data.custom_markup_ or 0,
    }


# ──────────────────────────────────────────────────────────────
# SMALL HELPERS
# ──────────────────────────────────────────────────────────────
def _to_flt(v) -> float:
    """robust `float` cast that strips stray symbols and handles None"""
    if v in (None, ""):
        return 0.0
    if isinstance(v, str):
        v = "".join(ch for ch in v if ch.isdigit() or ch in ".-")
    return flt(v)


# Brand Summary columns margin / margin_percent / std_margin_percent are
# decimal(21,9) → max ±999,999,999,999.999999999. Unbounded arithmetic on
# very small denominators (e.g. effective_ts near 0) produces values that
# blow past that range and raise MySQL 1264 "Out of range value" on save.
_DEC_21_9_MAX = 999_999_999_999.0

def _clamp_21_9(v) -> float:
    """Clamp to the representable range of a decimal(21,9) column."""
    n = flt(v)
    if n > _DEC_21_9_MAX:
        return _DEC_21_9_MAX
    if n < -_DEC_21_9_MAX:
        return -_DEC_21_9_MAX
    return n


# ── Near-zero denominators ────────────────────────────────────────────
# A selling total of exactly zero is legitimate and common: a line given
# away free (custom_markup_ = -100%), or a brand whose every line is
# zero-priced. But the pipeline REACHES that zero by adding and
# subtracting independently-rounded intermediates (cogs + markup,
# ts - discount, adjusted_cost + markup), so it routinely lands on a
# residue like -0.0004 instead of a true 0.0.
#
# `if selling` / `if effective_ts` does NOT catch that — -0.0004 is
# truthy — so margin% = value / -0.0004 * 100 blew up to 1,071,349,875%
# on QN-LLC-26-01200 (support ticket 2026-08-21) while the Brand Summary
# grid, rounding to 2 decimals, displayed that same total_selling as a
# perfectly innocent "0.00". That mismatch is why the report looked
# inexplicable: the cause sat two decimal places below what the UI shows.
#
# Anything below half a fils is not money. Treat it as zero.
_ZERO_TOL = 0.005


def _snap_zero(v) -> float:
    """Collapse a sub-fils rounding residue to a true 0.0."""
    n = flt(v)
    return 0.0 if abs(n) < _ZERO_TOL else n


def _safe_pct(numerator, denominator) -> float:
    """percentage = numerator / denominator * 100, guarded against a
    near-zero denominator.

    Use this INSTEAD OF the `flt(n / d * 100, 4) if d else 0` idiom
    anywhere in this module. The bare truthiness test only rejects an
    EXACT zero, so sub-fils residues sail through and explode into the
    billions — which is precisely the defect this replaced.
    """
    d = flt(denominator)
    if abs(d) < _ZERO_TOL:
        return 0.0
    return flt(flt(numerator) / d * 100, 4)


# Every decimal(21,9) margin-family field that is derived by dividing by a
# selling price / cost that can be near-zero — and therefore can overflow
# MySQL 1264 on save. The per-item calc guards only exact-zero denominators
# (`... if selling else 0`), so a tiny non-zero (e.g. 0.0001) still blows
# up; and Shipment and Margin.margin is written CLIENT-SIDE (quotation.js
# copies item.custom_margin_ into it) with no clamp at all.
_CLAMP_FIELDS = {
    "items": ("custom_margin_", "custom_markup_"),
    "custom_shipment_and_margin": ("margin", "std_margin", "ship_air", "ship_sea"),
    "custom_brand_summary": ("margin", "margin_percent", "std_margin_percent"),
    "custom_quotation_brand_summary": ("margin", "margin_percent", "std_margin_percent"),
}


def clamp_decimal_overflow_fields(doc, method=None):
    """validate hook — last line of defence against MySQL 1264
    "Out of range value for column 'margin'" on Quotation save.

    Runs server-side AFTER the client sets values (quotation.js) and after
    the per-item calc, so it catches BOTH the server-computed item
    percentages and the JS-populated Shipment and Margin rows before the
    row is inserted. Support ticket 2026-07-27: a brand whose selling
    total is ~0 makes margin% = value/selling*100 overflow decimal(21,9).
    """
    for table, fields in _CLAMP_FIELDS.items():
        for row in (doc.get(table) or []):
            for fn in fields:
                if row.get(fn) is not None:
                    row.set(fn, _clamp_21_9(row.get(fn)))


# ──────────────────────────────────────────────────────────────
# 1)  PER-ITEM CALCULATION  (server-side — single source of truth)
#     Verified formula from client spreadsheet (ERP_Next.ods)
# ──────────────────────────────────────────────────────────────
def calc_item_totals(it):
    qty = max(cint(it.qty), 1)

    # EXW / DDP: customer collects / delivers themselves, so no Air % or
    # Sea % shipping charge applies — always zero-rated, regardless of
    # whatever value is sitting on shipping_per (manual entry, stale bulk
    # import row, etc.). This is the single authoritative enforcement
    # point since every calc_item_totals() caller (Draft save pipeline,
    # submitted-quote "Update Items" flow) routes through here.
    if it.custom_shipping_mode in ("EXW", "DDP"):
        it.shipping_per = 0

    std_price = _to_flt(it.custom_standard_price_)
    sp        = _to_flt(it.custom_special_price)

    # Skip calculation if no custom pricing is configured (no Item Price setup).
    # Preserve manually entered rate/amount so they don't get zeroed out on save.
    if not std_price and not sp:
        # ... but DO clear the price-derived charges. Each is a percentage OF
        # a price (incentive and reward off special_price, shipping off
        # standard_price), so with no price they are definitionally zero.
        # Returning early used to leave whatever was stored by an earlier save
        # made while the row still had a price, and recalc_doc_totals sums
        # those stale figures straight into custom_total_incentive_new /
        # custom_total_reward_new / custom_total_shipping_new — crediting the
        # quote for a row that now contributes nothing.
        #
        # Only the computed VALUES are cleared; the percentages the user typed
        # are left alone, so each figure comes back on its own once a price is
        # entered again.
        #
        # custom_markup_value / custom_cogs / custom_selling_price are
        # deliberately NOT cleared here: unlike the charges above they are not
        # definitionally zero when a manual rate has been entered, and
        # protecting exactly that case is why this early return exists.
        it.custom_incentive_value = 0
        it.reward = 0
        it.shipping = 0
        return

    # Layer 1: percentage-based charges (total values)
    shipping  = flt(_to_flt(it.shipping_per)      * std_price / 100 * qty, 4)
    finance   = flt(_to_flt(it.custom_finance_)   * sp        / 100 * qty, 4)
    transport = flt(_to_flt(it.custom_transport_)  * std_price / 100 * qty, 4)
    reward    = flt(_to_flt(it.reward_per)         * sp        / 100 * qty, 4)

    # Layer 2: base amount
    base_amt = flt(sp * qty + shipping + finance + transport + reward, 4)

    # Layer 3: incentive on special price
    incentive = flt(_to_flt(it.custom_incentive_) * sp * qty / 100, 4)

    # Layer 4: customs on (base + incentive)
    cogs_before_customs = flt(base_amt + incentive, 4)
    customs = flt(_to_flt(it.custom_customs_) * cogs_before_customs / 100, 4)

    # Layer 5: COGS = base + incentive + customs
    cogs = flt(cogs_before_customs + customs, 4)

    # Layer 6: markup on COGS (after customs)
    markup = flt(_to_flt(it.custom_markup_) * cogs / 100, 4)

    # Final values.
    # _snap_zero: with custom_markup_ = -100 the intent is "give this line
    # away free", i.e. markup == -cogs and selling == 0. cogs and markup are
    # rounded separately, so the sum can miss zero by a sub-fils residue.
    selling = _snap_zero(flt(cogs + markup, 4))         # selling = cogs + markup

    # Margin: selling - cogs = markup (margin is the profit from markup)
    margin_val = flt(selling - cogs, 4)
    margin_pct = _safe_pct(margin_val, selling)

    per_unit_selling = flt(selling / qty, 4)

    it.update({
        "shipping":               shipping,
        "custom_finance_value":   finance,
        "custom_transport_value": transport,
        "reward":                 reward,
        "custom_incentive_value": incentive,
        "custom_markup_value":    markup,
        "custom_cogs":            cogs,
        "custom_total_":          selling,
        "custom_customs_value":   customs,
        "custom_selling_price":   selling,
        "custom_margin_":         margin_pct,
        "custom_margin_value":    margin_val,
        "custom_special_rate":    per_unit_selling,
        "rate":                   per_unit_selling,
        "amount":                 selling,
        # Reset discount fields so stale values don't trigger
        # distribute_discount_server on every save.
        # The pipeline will re-apply discount if parent has one.
        "custom_discount_amount_value": 0,
        "custom_discount_amount_qty":   0,
    })


# ──────────────────────────────────────────────────────────────
# 2)  BRAND SUMMARY  (server-side — replaces JS calculate_brand_summary)
# ──────────────────────────────────────────────────────────────
def rebuild_brand_summary(doc):
    buckets = {}

    for it in doc.items:
        # Group no-brand items under a None sentinel (NOT the string
        # "Unbranded"): the Brand Summary `brand` column is a Link to
        # Brand, and there is no Brand named "Unbranded", so persisting
        # that string fails link validation — which blocks saving,
        # notably on bulk Data Import where item.brand is often empty.
        # The sentinel is mapped back to a blank Link value on append.
        b = it.brand or None
        if b not in buckets:
            buckets[b] = {
                "shipping": 0, "shipping_percent": 0,
                "finance": 0, "finance_percent": 0,
                "processing": 0, "processing_percent": 0,
                "reward": 0, "reward_percent": 0,
                "incentive": 0, "incentive_percent": 0,
                "customs": 0, "customs_percent": 0,
                "buying_price": 0,
                "total_cost": 0, "total_selling": 0,
                "std_margin_weighted_sum": 0, "selling_weight_sum": 0,
                "cnt": 0,
            }

        bk = buckets[b]
        qty = max(cint(it.qty), 1)
        sp = _to_flt(it.custom_special_price)

        bk["shipping"]           += _to_flt(it.shipping)
        bk["shipping_percent"]   += _to_flt(it.shipping_per)
        bk["finance"]            += _to_flt(it.custom_finance_value)
        bk["finance_percent"]    += _to_flt(it.custom_finance_)
        bk["processing"]         += _to_flt(it.custom_transport_value)
        bk["processing_percent"] += _to_flt(it.custom_transport_)
        bk["reward"]             += _to_flt(it.reward)
        bk["reward_percent"]     += _to_flt(it.reward_per)
        bk["incentive"]          += _to_flt(it.custom_incentive_value)
        bk["incentive_percent"]  += _to_flt(it.custom_incentive_)
        bk["customs"]            += _to_flt(it.custom_customs_value)
        bk["customs_percent"]    += _to_flt(it.custom_customs_)
        bk["buying_price"]       += flt(sp * qty, 4)
        bk["total_cost"]         += _to_flt(it.custom_cogs)
        bk["total_selling"]      += _to_flt(it.custom_selling_price)
        bk["std_margin_weighted_sum"] += _to_flt(it.std_margin_per) * _to_flt(it.custom_selling_price)
        bk["selling_weight_sum"]     += _to_flt(it.custom_selling_price)
        bk["cnt"]                += 1

    # Get additional discount to distribute to brand summary
    addl_discount = flt(doc.discount_amount) if flt(doc.additional_discount_percentage) > 0 or flt(doc.discount_amount) > 0 else 0
    total_selling_all = sum(d["total_selling"] for d in buckets.values())

    doc.set("custom_quotation_brand_summary", [])
    for brand, d in buckets.items():
        n = d.pop("cnt") or 1
        ts = d["total_selling"]
        tc = d["total_cost"]

        # Distribute additional discount pro-rata by brand selling share
        brand_addl = 0
        if addl_discount > 0 and total_selling_all > 0:
            brand_addl = flt(addl_discount * ts / total_selling_all, 4)

        effective_ts = _snap_zero(flt(ts - brand_addl, 4))
        brand_margin_pct = _safe_pct(effective_ts - tc, effective_ts)

        # Weighted average std margin for the brand
        std_margin_percent = (
            d["std_margin_weighted_sum"] / d["selling_weight_sum"]
            if d["selling_weight_sum"] > 0 else 0
        )

        doc.append("custom_quotation_brand_summary", {
            "brand":              brand or "",
            "buying_price":       flt(d["buying_price"], 4),
            "shipping":           flt(d["shipping"], 4),
            "shipping_percent":   flt(d["shipping_percent"] / n, 4),
            "finance":            flt(d["finance"], 4),
            "finance_percent":    flt(d["finance_percent"] / n, 4),
            "processing":         flt(d["processing"], 4),
            "processing_percent": flt(d["processing_percent"] / n, 4),
            "reward":             flt(d["reward"], 4),
            "reward_percent":     flt(d["reward_percent"] / n, 4),
            "incentive":          flt(d["incentive"], 4),
            # Weighted brand incentive %, NOT the average of the rows' own
            # Incentive (%): each row's % is defined against its own Special
            # Price x Qty, and the incentive amount is distributed by AMOUNT,
            # so the rows' %s differ wildly (e.g. 2.8 .. 72.9 on the same
            # brand) and their average is meaningless. Reconcile to the same
            # base the header (custom_incentive_) and the doc-total
            # (custom_total_incentive_percent_new) already use -- buying_price
            # (#0527, QN-FZCO-26-00577-3: average showed 38.62% vs true 9.47%).
            "incentive_percent":  _safe_pct(d["incentive"], d["buying_price"]),
            "customs":            flt(d["customs"], 4),
            "customs_":           flt(d["customs_percent"] / n, 4),
            "total_cost":         flt(tc, 4),
            "total_selling":      flt(effective_ts, 4),
            "margin":             _clamp_21_9(flt(effective_ts - tc, 4)),
            "margin_percent":     _clamp_21_9(brand_margin_pct),
            "std_margin_percent": _clamp_21_9(flt(std_margin_percent, 2)),
            "approval_status":    "",
        })


# ──────────────────────────────────────────────────────────────
# 3)  DOC-LEVEL TOTALS  (replaces old recalc_totals)
# ──────────────────────────────────────────────────────────────
def recalc_doc_totals(doc):
    totals = {
        "shipping": 0, "finance": 0, "transport": 0, "reward": 0,
        "incentive": 0, "customs": 0, "cost": 0, "selling": 0,
        "buying_price": 0,
    }

    for it in doc.items:
        totals["shipping"]     += _to_flt(it.shipping)
        totals["finance"]      += _to_flt(it.custom_finance_value)
        totals["transport"]    += _to_flt(it.custom_transport_value)
        totals["reward"]       += _to_flt(it.reward)
        totals["incentive"]    += _to_flt(it.custom_incentive_value)
        totals["customs"]      += _to_flt(it.custom_customs_value)
        totals["cost"]         += _to_flt(it.custom_cogs)
        totals["selling"]      += _to_flt(it.custom_selling_price)

        qty = max(cint(it.qty), 1)
        sp = _to_flt(it.custom_special_price)
        totals["buying_price"] += flt(sp * qty, 4)

    ts = totals["selling"]
    tc = totals["cost"]

    # Account for ERPNext's Additional Discount when calculating margin.
    # MUST use percentage as source of truth on server side because ERPNext's
    # set_discount_amount() in validate always overwrites discount_amount from
    # percentage using ERPNext's own grand_total (which differs from ours).
    # We derive discount_amount from percentage using our own ts.
    addl_discount = 0
    if flt(doc.additional_discount_percentage) > 0:
        addl_discount = flt(ts * flt(doc.additional_discount_percentage) / 100, 4)
        doc.discount_amount = addl_discount
    elif flt(doc.discount_amount) > 0:
        addl_discount = flt(doc.discount_amount)
        doc.additional_discount_percentage = _safe_pct(addl_discount, ts)

    # ── Pro-rata distribution of Additional Discount to each item row ──
    # Allocate based on each item's share of total selling value.
    # Also recalculate per-item margin after addl discount.
    for it in doc.items:
        if addl_discount > 0 and ts > 0:
            item_selling = _to_flt(it.custom_selling_price)
            share = item_selling / ts if ts else 0
            item_addl = flt(addl_discount * share, 4)
            it.custom_addl_discount_amount = item_addl

            # Recalculate item margin including additional discount
            effective_item_selling = _snap_zero(flt(item_selling - item_addl, 4))
            item_cost = _to_flt(it.custom_cogs)
            it.custom_margin_value = flt(effective_item_selling - item_cost, 4)
            it.custom_margin_ = _safe_pct(it.custom_margin_value, effective_item_selling)
        else:
            it.custom_addl_discount_amount = 0

    effective_selling = _snap_zero(flt(ts - addl_discount, 4))

    # Total Margin amount comes from the Brand Summary if it has rows
    # (keeps it consistent with the per-brand values shown to the user),
    # otherwise we compute from selling - cost. EITHER way, the margin
    # PERCENT must be derived as (margin / effective_selling × 100).
    # The previous version added each brand's margin_percent which is
    # mathematically wrong — percents on different bases don't sum to a
    # meaningful percent. For a quote with 7 brands at ~21% each it
    # produced ~147% (customer reported 151.05% on QN-LLC-26-00316).
    bs_margin = 0
    has_brand_summary = False
    for bs_row in (doc.get("custom_quotation_brand_summary") or []):
        bs_margin += flt(bs_row.margin)
        has_brand_summary = True

    if has_brand_summary:
        margin = flt(bs_margin, 4)
    else:
        margin = flt(effective_selling - tc, 4)
    margin_pct = _safe_pct(margin, effective_selling)

    doc.custom_total_shipping_new       = flt(totals["shipping"], 4)
    doc.custom_total_finance_new        = flt(totals["finance"], 4)
    doc.custom_total_transport_new      = flt(totals["transport"], 4)
    doc.custom_total_reward_new         = flt(totals["reward"], 4)
    doc.custom_total_incentive_new      = flt(totals["incentive"], 4)
    # Weighted average of the rows' own Incentive (%), NOT their sum: each
    # row's percentage is defined against its own Special Price x Qty (see
    # calc_item_totals), so the only base that reconciles back to the rows is
    # that same total — totals["buying_price"]. Summing the row percentages is
    # the mistake that produced ~147% from 7 brands at ~21% on QN-LLC-26-00316;
    # see the Total Margin comment above.
    doc.custom_total_incentive_percent_new = _safe_pct(
        totals["incentive"], totals["buying_price"]
    )
    doc.custom_total_customs_new        = flt(totals["customs"], 4)
    doc.custom_total_margin_new         = margin
    doc.custom_total_margin_percent_new = margin_pct
    doc.custom_total_cost_new           = flt(tc, 4)
    doc.custom_total_selling_new        = flt(effective_selling, 4)
    doc.custom_total_buying_price       = flt(totals["buying_price"], 4)

    # Sync standard ERPNext total fields from our pipeline's rate/amount.
    # ERPNext's calculate_taxes_and_totals runs in validate (before our
    # before_save pipeline), so standard totals are stale at this point.
    conversion_rate = flt(doc.conversion_rate) or 1
    total_qty = sum(max(cint(it.qty), 1) for it in doc.items)
    item_amount_sum = sum(flt(it.amount) for it in doc.items)

    # Sammish 2026-06-18 (QN-KSA-26-00169): user reported "Net Total field
    # equals Total even when Additional Discount is set". Root cause was
    # this block ALWAYS writing net_total = item_amount_sum regardless of
    # doc.apply_discount_on. ERPNext semantics:
    #   apply_on = "Net Total"  → discount reduces net_total; taxes on
    #                              the discounted base. (KSA VAT / India
    #                              GST default — discount lowers the
    #                              taxable supply value.)
    #   apply_on = "Grand Total" → net_total stays at item_amount_sum;
    #                              discount comes off at grand_total
    #                              after tax. (Mostly cash-discount or
    #                              "rounding adjustment" use cases.)
    # Bug surface verified on prod 2026-06-18: 301 Quotations with
    # apply_on=Net Total + discount>0 had grand_total inflated by
    # tax × discount (e.g. QN-KSA-26-00169 stored 113,640.74 vs correct
    # 113,490.74 — 150 SAR overcharge from 15% × 1000 discount).
    apply_on_net_total = (doc.apply_discount_on or "Grand Total") == "Net Total"
    discounted_total = flt(item_amount_sum - addl_discount, 4) if apply_on_net_total else flt(item_amount_sum, 4)

    doc.total_qty      = flt(total_qty, 4)
    doc.total          = flt(item_amount_sum, 4)
    doc.net_total      = discounted_total
    doc.base_total     = flt(item_amount_sum * conversion_rate, 4)
    doc.base_net_total = flt(discounted_total * conversion_rate, 4)

    # ── Recalculate taxes from the Taxes table ──
    # ERPNext's calculate_taxes_and_totals ran during validate with stale
    # item amounts.  Recompute each tax row based on our updated net_total.
    net_after_discount = flt(item_amount_sum - addl_discount, 4)
    total_taxes = 0
    for tax_row in (doc.get("taxes") or []):
        if tax_row.charge_type == "On Net Total":
            # Rahul Avientek 2026-06-16 (QN-LTD-26-02267): Draft showed
            # ₹11,939 tax, Submit jumped to ₹18,572. Root cause was THIS
            # line previously doing `tax_row.rate × net_after_discount`
            # which ignored each item's `item_tax_rate` JSON.
            #
            # Items can carry per-row GST classification via
            # `item_tax_template` → `item_tax_rate` (e.g. one line at
            # GST 18%, another at GST 28%). ERPNext's server-side
            # `calculate_taxes_and_totals` honors this; our pipeline
            # was overriding with a flat parent rate, so Draft saved a
            # wrong total. On Submit `run_calculation_pipeline` is
            # gated by `docstatus != 0` so the correct value re-emerged
            # — same doc, two answers.
            #
            # Fix: mirror ERPNext's per-item logic. For each item, look
            # up its rate for THIS tax row's account_head in
            # `item_tax_rate`. Fall back to `tax_row.rate` if not
            # present (single-rate quotes behave identically to before).
            #
            # Sammish 2026-06-18: also reduce per-item amount by its
            # share of the Additional Discount when apply_on=Net Total
            # — otherwise tax is computed on the pre-discount base
            # while net_total is post-discount, leaving the customer
            # overcharged by (tax_rate × discount).
            account = tax_row.account_head
            tax_for_row = 0.0
            for it in (doc.get("items") or []):
                amount = flt(it.amount)
                if not amount:
                    continue
                if apply_on_net_total and addl_discount > 0 and item_amount_sum > 0:
                    item_addl = flt(addl_discount * amount / item_amount_sum, 4)
                    amount = flt(amount - item_addl, 4)
                rate_for_item = flt(tax_row.rate)
                try:
                    itax = it.get("item_tax_rate") or "{}"
                    if isinstance(itax, str):
                        itax = json.loads(itax) if itax else {}
                    if account in itax:
                        rate_for_item = flt(itax[account])
                except Exception:
                    pass
                tax_for_row += amount * rate_for_item / 100
            tax_row.tax_amount = flt(tax_for_row, 4)
        elif tax_row.charge_type == "On Previous Row Total" and tax_row.row_id:
            prev_idx = cint(tax_row.row_id) - 1
            prev_rows = doc.get("taxes") or []
            if 0 <= prev_idx < len(prev_rows):
                prev_total = flt(prev_rows[prev_idx].total)
                tax_row.tax_amount = flt(flt(tax_row.rate) * prev_total / 100, 4)
        elif tax_row.charge_type == "On Previous Row Amount" and tax_row.row_id:
            prev_idx = cint(tax_row.row_id) - 1
            prev_rows = doc.get("taxes") or []
            if 0 <= prev_idx < len(prev_rows):
                tax_row.tax_amount = flt(flt(tax_row.rate) * flt(prev_rows[prev_idx].tax_amount) / 100, 4)
        # "Actual" charge_type: tax_amount is a fixed value, keep as-is

        tax_row.base_tax_amount = flt(tax_row.tax_amount * conversion_rate, 4)
        tax_row.total = flt(net_after_discount + sum(
            flt(t.tax_amount) for t in (doc.get("taxes") or [])[:doc.taxes.index(tax_row) + 1]
        ), 4)
        tax_row.base_total = flt(tax_row.total * conversion_rate, 4)
        total_taxes += flt(tax_row.tax_amount)

    doc.total_taxes_and_charges = flt(total_taxes, 4)
    doc.base_total_taxes_and_charges = flt(total_taxes * conversion_rate, 4)

    doc.grand_total    = flt(net_after_discount + total_taxes, 4)
    doc.base_grand_total = flt(doc.grand_total * conversion_rate, 4)
    doc.rounded_total  = round(doc.grand_total)
    doc.base_rounded_total = round(doc.base_grand_total)

    # ── Recalculate payment schedule to match updated grand_total ──
    # ERPNext calculates payment schedule during validate (before our pipeline),
    # so amounts are stale when grand_total changes here.
    gt = flt(doc.rounded_total or doc.grand_total)
    base_gt = flt(doc.base_rounded_total or doc.base_grand_total)
    for ps in (doc.get("payment_schedule") or []):
        portion = flt(ps.invoice_portion) or 100
        ps.payment_amount = flt(gt * portion / 100, 4)
        ps.base_payment_amount = flt(base_gt * portion / 100, 4)
        ps.outstanding = ps.payment_amount


    # ── Sync item-level ERPNext fields (net_rate, net_amount, base_*) ──
    # ERPNext's validate already set these from the OLD rate before our
    # pipeline changed it, so they are stale.  Recompute from our rate.
    for it in doc.items:
        qty = max(cint(it.qty), 1)
        rate = flt(it.rate)
        amount = flt(it.amount)

        # Distribute additional discount to item level
        if addl_discount and item_amount_sum:
            item_addl_disc = flt(addl_discount * amount / item_amount_sum, 4)
        else:
            item_addl_disc = 0

        net_amount = flt(amount - item_addl_disc, 4)
        net_rate   = flt(net_amount / qty, 4) if qty else 0

        it.net_rate       = net_rate
        it.net_amount     = net_amount
        it.base_rate      = flt(rate * conversion_rate, 4)
        it.base_amount    = flt(amount * conversion_rate, 4)
        it.base_net_rate  = flt(net_rate * conversion_rate, 4)
        it.base_net_amount = flt(net_amount * conversion_rate, 4)


# ──────────────────────────────────────────────────────────────
# 4)  DISTRIBUTE INCENTIVE  (server-side — replaces JS distribute_incentive)
# ──────────────────────────────────────────────────────────────
def distribute_incentive_server(doc):
    """Distribute parent-level incentive across items.
    Must be called AFTER calc_item_totals has populated fields on each item.
    """
    mode = doc.get("custom_distribute_incentive_based_on")
    if mode == "Distributed Manually":
        return

    total_incentive = _to_flt(doc.custom_incentive_amount)
    if total_incentive < 0:
        return  # Only reject negative values, allow 0 to clear incentives

    items = doc.items or []
    if not items:
        return

    # Sum of all item (sp * qty) for proportional distribution. Only the
    # proportional split needs it as a divisor, so a zero base blocks a real
    # distribution but must NOT block a clear-to-zero — otherwise a quote whose
    # prices were removed keeps its old per-row incentive forever.
    total_sp = sum(flt(_to_flt(it.custom_special_price) * max(cint(it.qty), 1)) for it in items)
    if not total_sp and total_incentive:
        return

    for it in items:
        qty = max(cint(it.qty), 1)
        sp = _to_flt(it.custom_special_price)
        cogs = _to_flt(it.custom_cogs)
        old_incentive = _to_flt(it.custom_incentive_value)  # incentive already in cogs

        # Distribute incentive
        if not total_incentive:
            # Clearing. Short-circuit before the proportional branch, which
            # would divide by a total_sp that is allowed to be zero here.
            row_incentive = 0.0
        elif mode == "Distributed Equally":
            row_incentive = flt(total_incentive / len(items), 4)
        else:  # "Amount" — proportional to sp * qty
            row_incentive = flt((sp * qty / total_sp) * total_incentive, 4)

        # Remove old incentive from cogs, then add new distributed incentive
        cogs_without_incentive = flt(cogs - old_incentive, 4)
        adjusted_cost = flt(cogs_without_incentive + row_incentive, 4)

        # Re-derive the markup from its PERCENTAGE against the ADJUSTED
        # cost — do NOT carry over the absolute custom_markup_value.
        #
        # That absolute was computed by calc_item_totals against the
        # PRE-distribution cogs. Moving the incentive component changes the
        # cost but left the absolute untouched, so the two stopped
        # cancelling: a line marked custom_markup_ = -100 ("give it away
        # free") silently acquired a price equal to the incentive shifted
        # into it. On QN-LLC-26-01200 the incentive was already distributed,
        # so the drift was only -0.0004 — enough to make margin% explode to
        # 1,071,349,875% — but on a fresh save the same defect prices a
        # free-of-charge line at hundreds of dirhams.
        #
        # markup% is the pricing lever everywhere else in this module
        # (calc_item_totals derives the absolute from it, and the JS
        # back-solve writes both), so holding the PERCENTAGE invariant
        # across redistribution is the self-consistent choice.
        markup = flt(_to_flt(it.custom_markup_) * adjusted_cost / 100, 4)

        # Selling = adjusted cost + markup
        selling = _snap_zero(flt(adjusted_cost + markup, 4))
        per_unit_selling = flt(selling / qty, 4)

        # Margin
        margin_val = flt(selling - adjusted_cost, 4)
        margin_pct = _safe_pct(margin_val, selling)

        it.update({
            "custom_incentive_value": row_incentive,
            "custom_incentive_":     _safe_pct(row_incentive, sp * qty),
            "custom_cogs":           adjusted_cost,
            # Persist the re-derived absolute too, so custom_markup_value
            # stays consistent with cogs/selling instead of silently
            # describing a cost basis that no longer exists.
            "custom_markup_value":   markup,
            "custom_selling_price":  selling,
            "custom_total_":         selling,
            "custom_special_rate":   per_unit_selling,
            "rate":                  per_unit_selling,
            "amount":                selling,
            "custom_margin_value":   margin_val,
            "custom_margin_":        margin_pct,
        })


# ──────────────────────────────────────────────────────────────
# 4b) DISTRIBUTE DISCOUNT (server-side — auto-redistributes on save)
# ──────────────────────────────────────────────────────────────
def distribute_discount_server(doc):
    """Distribute parent-level discount across items proportionally.
    Must be called AFTER calc_item_totals and distribute_incentive_server.
    """
    total_discount = _to_flt(doc.custom_discount_amount_value)
    if total_discount < 0:
        return  # Only reject negative values

    items = doc.items or []
    if not items:
        return

    # Calculate total selling value (before discount) for proportional distribution
    total_selling = sum(flt(_to_flt(it.custom_selling_price)) for it in items)
    if total_selling <= 0:
        return

    for it in items:
        qty = max(cint(it.qty), 1)
        selling = _to_flt(it.custom_selling_price)
        cogs = _to_flt(it.custom_cogs)

        # Proportional discount based on selling price
        share = selling / total_selling if total_selling else 0
        item_discount = flt(total_discount * share, 4)

        # New selling after discount
        new_selling = _snap_zero(flt(selling - item_discount, 4))
        if new_selling < 0:
            new_selling = 0

        new_rate = flt(new_selling / qty, 4) if qty else 0

        # Margin recalculation (after discount)
        margin_val = flt(new_selling - cogs, 4)
        if margin_val < 0:
            margin_val = 0
        margin_pct = _safe_pct(margin_val, new_selling)

        it.update({
            "custom_discount_amount_value": flt(item_discount / qty, 4) if qty else 0,
            "custom_discount_amount_qty": item_discount,
            "custom_selling_price": new_selling,
            "custom_total_": new_selling,
            "custom_special_rate": new_rate,
            "rate": new_rate,
            "amount": new_selling,
            "custom_margin_value": margin_val,
            "custom_margin_": margin_pct,
        })


# ── Server Script: "Quot - Item Tax Template" ──
# DocType Event: Quotation, Before Validate
def validate_item_tax_template(doc, method=None):
    """Auto-fill Item Tax Template from Item master, then hard-require
    it for Avientek Electronics Trading PVT. LTD."""
    from avientek.events.utils import autofill_item_tax_template
    required = "Avientek Electronics Trading PVT. LTD" if doc.company == "Avientek Electronics Trading PVT. LTD" else None
    autofill_item_tax_template(doc, required_company=required)


# ──────────────────────────────────────────────────────────────
# 4c) DISCOUNT / INCENTIVE — Percentage <-> Amount sync for the
#     submitted-doc ("Approved for Update") bypass endpoints below.
#     Mirrors the client-side math in custom_apply_discount /
#     custom_apply_incentive (quotation.js) exactly, so the server
#     produces the same number the button preview already showed.
# ──────────────────────────────────────────────────────────────
def _sync_discount_fields(doc):
    """Keep custom_discount_ (%) and custom_discount_amount_value ($)
    consistent against the CURRENT item total. Percentage is
    authoritative when custom_discount_type == "Percentage" — the
    amount is recomputed from it, so a discount entered as a percentage
    automatically rebases when the item set (and therefore total
    selling value) changes, e.g. via Update Items adding/removing rows.
    Amount is authoritative otherwise — the percentage is recomputed
    from it purely for display; distribute_discount_server() always
    redistributes whatever amount ends up here across the current items.
    """
    total_selling = sum(flt(it.custom_selling_price) for it in doc.items)
    if (doc.custom_discount_type or "Amount") == "Percentage":
        if flt(doc.custom_discount_) and total_selling > 0:
            doc.custom_discount_amount_value = flt(total_selling * flt(doc.custom_discount_) / 100, 4)
    else:
        if flt(doc.custom_discount_amount_value):
            doc.custom_discount_ = _safe_pct(doc.custom_discount_amount_value, total_selling)


def _sync_incentive_fields(doc):
    """Same idea as _sync_discount_fields() for Incentive — driven by
    total (Special Price x Qty), matching custom_apply_incentive."""
    total_sp = sum(flt(it.custom_special_price) * (flt(it.qty) or 1) for it in doc.items)
    if (doc.custom_incentive_type or "Percentage") == "Percentage":
        if flt(doc.custom_incentive_) and total_sp > 0:
            doc.custom_incentive_amount = flt(total_sp * flt(doc.custom_incentive_) / 100, 4)
    else:
        if flt(doc.custom_incentive_amount):
            doc.custom_incentive_ = _safe_pct(doc.custom_incentive_amount, total_sp)


def _guard_quotation_editable_for_update(doc):
    """Shared entry guard for update_items_selling_price() /
    apply_discount_on_submitted() / apply_incentive_on_submitted() —
    previously duplicated (and, for the third check below, missing
    entirely) across all three.

    Sridhar 2026-07-27 (BRD review, sammish — "confirm 'Approved for
    Update' is always pre-conversion, no SO/SI created yet"): checked
    the actual workflow transitions (seed_quotation_approval_v3_
    workflow.py) — "Request for Update" only requires workflow_state ==
    "Approved" plus the checkbox; nothing checks whether a Sales Order
    already exists against this Quotation. And creating a Sales Order
    does NOT change workflow_state at all — only ERPNext's own core
    `status` field moves to "Ordered" / "Partially Ordered". So a
    Quotation that already has a submitted Sales Order against it CAN
    still reach "Approved for Update" today — the answer to sammish's
    question is "not guaranteed by the workflow," not "confirmed
    impossible." Repricing/removing items in that state would desync
    the already-created Sales Order, which never sees the change.
    Blocking on `doc.status` here (reliable — ERPNext sets it via
    Quotation.set_status()/get_ordered_status() whenever a Sales Order
    references this Quotation) closes the gap rather than just noting
    it as an assumption.
    """
    if doc.docstatus != 1:
        frappe.throw(_("This action is only allowed on submitted Quotations."))
    if (doc.workflow_state or "") != "Approved for Update":
        frappe.throw(_(
            "This action can only be used while the Quotation is in the "
            "'Approved for Update' state."
        ))
    if doc.status in ("Ordered", "Partially Ordered"):
        frappe.throw(_(
            "This Quotation already has a Sales Order created against it "
            "({0}). Editing items or pricing here would desync the "
            "existing Sales Order, which will not reflect this change — "
            "not allowed."
        ).format(doc.status))


def _finalize_submitted_quotation_save(doc, notify_discount_incentive_reapply=False):
    """Shared save tail for every "Approved for Update" bypass endpoint
    (update_items_selling_price, apply_discount_on_submitted,
    apply_incentive_on_submitted). See update_items_selling_price's
    docstring for the full trace of why doc.save() is safe here and why
    the ordering below matters (validate/before_save hooks never fire
    for a docstatus 1->1 save, so anything from that chain that still
    matters — GST/tax-template validation, Sales Taxes and Charges,
    payment schedule — has to be called explicitly, in the right order,
    since nothing does it automatically).

    Incentive is applied before Discount (matches run_calculation_
    pipeline's Draft-time order) since Discount distributes across the
    incentive-adjusted selling price, not the pre-incentive one.

    Sridhar 2026-07-27 (BRD review, sammish — "must-answer": does
    repricing on a submitted quote re-trigger margin approval?):
    set_margin_flags() is the ONLY thing that recomputes
    custom_auto_approve_ok / custom_level_1_approve_ok and each Brand
    Summary row's approval_status, and — same root cause as everything
    else in this docstring — it's normally called from
    run_calculation_pipeline (a before_save hook), which never fires
    here. Without this call, a repriced-down quote would keep whatever
    STALE approve-ok flags it had from before the edit (rebuild_brand_
    summary() even resets approval_status to blank), so the mandatory
    "Send for Approval" step a user must take to leave "Approved for
    Update" would show an L1 reviewer incorrect/blank margin data and
    could let a quote that actually needs Level 2 slip through on an L1
    approval alone. Calling it here — right after Brand Summary is
    rebuilt, since it reads doc.custom_quotation_brand_summary — closes
    that gap: the flags and Brand Summary the approver sees are always
    current as of the latest Update Items / Discount / Incentive save.
    """
    validate_item_tax_template(doc)

    had_incentive = flt(doc.custom_incentive_amount) > 0 or flt(doc.custom_incentive_) > 0
    had_discount = flt(doc.custom_discount_amount_value) > 0 or flt(doc.custom_discount_) > 0

    if had_incentive:
        _sync_incentive_fields(doc)
        distribute_incentive_server(doc)

    if had_discount:
        _sync_discount_fields(doc)
        distribute_discount_server(doc)

    if notify_discount_incentive_reapply and (had_incentive or had_discount):
        frappe.msgprint(
            _(
                "Discount / Incentive were automatically re-applied at "
                "their existing percentage against the updated items."
            ),
            alert=True,
            indicator="blue",
        )

    # Our own custom Brand Summary + parent total fields — separate from
    # ERPNext's native net_total/taxes/grand_total, which
    # calculate_taxes_and_totals() below derives straight from the
    # item.rate/amount fields already finalized above.
    rebuild_brand_summary(doc)

    # Re-evaluate margin approval against the NEW pricing — see the
    # docstring above. Must run after rebuild_brand_summary (reads its
    # output) and before doc.save() so the persisted flags/Brand
    # Summary are what an L1/L2 approver actually sees.
    was_auto_approve_ok = cint(doc.get("custom_auto_approve_ok"))
    set_margin_flags(doc)
    if was_auto_approve_ok and not cint(doc.custom_auto_approve_ok):
        need_l2 = not cint(doc.custom_level_1_approve_ok)
        frappe.msgprint(
            _(
                "This change dropped one or more brands below the auto-approve "
                "margin threshold — {0} approval will be required. Use "
                "'Send for Approval' when you're done editing; the approver "
                "will see the updated margin."
            ).format(_("Level 2") if need_l2 else _("Level 1")),
            title=_("Margin Approval Required"),
            indicator="orange",
        )

    recalc_doc_totals(doc)

    for idx, row in enumerate(doc.items, start=1):
        row.idx = idx

    # Standard ERPNext recalculation of Sales Taxes and Charges + net/
    # grand totals from the item rate/amount fields, matching default
    # ERPNext's own update_child_qty_rate call sequence. Must run last —
    # it's the only thing that correctly repopulates item.item_tax_rate
    # from item.item_tax_template (needed for a newly added item with a
    # different GST rate than the rest of the quote), and everything
    # above this point can still change item.rate/amount.
    doc.set_qty_as_per_stock_uom()
    doc.calculate_taxes_and_totals()
    # payment_schedule is the one field calculate_taxes_and_totals()
    # does NOT recompute (it's a separate method) — call explicitly so
    # it doesn't go stale relative to the just-corrected grand_total.
    doc.set_payment_schedule()
    doc.set_total_in_words()

    # Sridhar 2026-07-29 (found via downloaded-Excel review, QN-FZCO-26-00251
    # showing Taxable Value = 0 despite a real IGST amount already charged):
    # india_compliance (installed on test/production, NOT in this local
    # bench — see project_local_vs_prod_app_mismatch memory) sets
    # Quotation Item.taxable_value (= base_net_amount) from a hook on the
    # *child item doctype's* on_change event (gst_india/overrides/
    # transaction.py on_change_item), which only runs `update_taxable_values`
    # (and india_compliance's other GST recalculation: HSN validation,
    # item-wise tax detail, GST treatment) when frappe.flags.through_
    # update_item is True. That flag is only ever set BY that same
    # on_change_item hook, gated on child_item.flags.ignore_validate_
    # update_after_submit — which fires because ERPNext's own
    # update_child_qty_rate saves each child row INDIVIDUALLY
    # (child_item.save(...)). We instead mutate doc.items in memory and
    # do one parent-level doc.save() — cleaner, but the child rows'
    # on_change never fires, so india_compliance's flag never gets set,
    # so it silently skips its whole GST recalculation block and returns
    # early. Setting the flag ourselves reproduces the same effect
    # without switching to per-row saves. Harmless when india_compliance
    # isn't installed (frappe.flags is just a dict-like bag; nothing
    # reads this key if the app isn't there).
    frappe.flags.through_update_item = True

    # Same flag ERPNext's own update_child_qty_rate uses so a submitted
    # doc's non-allow_on_submit fields can be saved in place.
    doc.flags.ignore_validate_update_after_submit = True
    doc.save()


# ──────────────────────────────────────────────────────────────
# 5)  MASTER PIPELINE  (called from before_save hook)
# ──────────────────────────────────────────────────────────────
def _apply_manual_selling_rate(it, user_rate, discount_total=0.0, pre_discount_total=0.0):
    """Back-solve custom_markup_ so the formula stays stable across saves.

    When a parent-level discount exists, calc_item_totals + distribute_discount_server
    will reduce the rate on every save. We inflate the back-solved markup% target by
    the discount share so that on subsequent saves:
        calc_item_totals  →  pre_discount_rate
        distribute        →  pre_discount_rate − share  ≈  user_rate   (stable)

    custom_special_rate is always written as user_rate (what the user sees).
    """
    qty = max(cint(it.qty), 1)
    cogs = flt(it.custom_cogs)
    if cogs <= 0:
        return

    # Inflate target so post-discount matches user_rate:
    #   pre_rate = user_rate × T / (T − D)
    pre_discount_rate = user_rate
    if discount_total > 0 and pre_discount_total > discount_total:
        pre_discount_rate = flt(
            user_rate * pre_discount_total / (pre_discount_total - discount_total), 4
        )

    pre_discount_selling = flt(pre_discount_rate * qty, 4)
    user_selling = flt(user_rate * qty, 4)

    markup_val = flt(pre_discount_selling - cogs, 4)
    # cogs was divided by unguarded — a zero-cost line (no Item Price set up)
    # raised ZeroDivisionError and 500'd the Update Selling Price endpoint.
    markup_pct = _safe_pct(markup_val, cogs)
    margin_val = flt(user_selling - cogs, 4)
    margin_pct = _safe_pct(margin_val, user_selling)

    it.update({
        "custom_markup_":       markup_pct,           # inflated so formula is self-consistent
        "custom_markup_value":  markup_val,
        "custom_special_rate":  user_rate,            # final visible price
        "rate":                 user_rate,
        "custom_selling_price": user_selling,
        "custom_total_":        user_selling,
        "amount":               user_selling,
        "custom_margin_":       margin_pct,
        "custom_margin_value":  margin_val,
    })


def backfill_item_core_fields(doc):
    """Bulk-uploaded rows (Items grid "Bulk Edit" CSV upload / Data Import /
    API) never fire the item_code client trigger, so ERPNext's own "fetch item
    details" (item_name, uom, stock_uom, ...) never runs. Without this, save
    fails core's mandatory-field check ("Item Name is required" / "UOM is
    required") for every such row. (PR #13, ported to master 2026-07-08.)"""
    item_codes = {
        it.item_code for it in doc.items
        if it.item_code and (not it.item_name or not it.uom)
    }
    if not item_codes:
        return

    item_data = {
        row.name: row
        for row in frappe.get_all(
            "Item",
            filters={"name": ["in", list(item_codes)]},
            fields=["name", "item_name", "stock_uom", "description"],
        )
    }

    for it in doc.items:
        if not it.item_code:
            continue
        item = item_data.get(it.item_code)
        if not item:
            continue  # invalid item_code — core link validation will catch it
        if not it.item_name:
            it.item_name = item.item_name or it.item_code
        if not it.description:
            it.description = item.description or item.item_name
        if not it.uom:
            it.uom = item.stock_uom
            it.stock_uom = item.stock_uom
            it.conversion_factor = 1
            it.stock_qty = flt(it.qty) * 1


def _default_shipping_per_for_mode(mode, defaults):
    """Pick the correct starting shipping_per for a Shipping Mode from an
    Item Price defaults dict (see get_item_defaults). EXW/DDP are always
    zero-rated and never pull a percentage from the Item Price master —
    the customer collects/pays for their own shipping under those terms.
    Blank/unrecognised modes fall back to Air, matching the pre-EXW/DDP/DDU
    default."""
    if mode in ("EXW", "DDP"):
        return 0
    if mode == "Sea":
        return flt(defaults.get("shipping_per_sea")) or 0
    if mode == "DDU":
        return flt(defaults.get("shipping_per_ddu")) or 0
    return flt(defaults.get("shipping_per_air")) or 0


def backfill_item_price_defaults(doc):
    """Same root cause as backfill_item_core_fields: rows added via bulk CSV
    upload / Data Import / API never fire the item_code trigger, so
    get_item_defaults() never ran. Fill Item Price / Brand pricing server-side
    for any row that has an item_code but no standard price yet, before
    calc_item_totals runs. Reuses get_item_defaults() so the company-specific /
    fallback lookup stays identical to the interactive path."""
    for it in doc.items:
        if not it.item_code or _to_flt(it.custom_standard_price_):
            continue  # no item, or already priced (user/JS already set it)

        defaults = get_item_defaults(
            it.item_code,
            doc.selling_price_list,
            doc.currency,
            doc.price_list_currency,
            doc.plc_conversion_rate,
            doc.company,
        )
        if defaults.get("no_price_for_company") or not defaults.get("custom_standard_price_"):
            continue  # no Item Price — leave at 0, don't block save

        it.custom_standard_price_ = defaults["custom_standard_price_"]
        if not _to_flt(it.custom_special_price):
            it.custom_special_price = defaults["custom_special_price"]
        if not _to_flt(it.shipping_per):
            mode = it.custom_shipping_mode or doc.custom_shipping_mode
            it.shipping_per = _default_shipping_per_for_mode(mode, defaults)
        if not _to_flt(it.custom_transport_):
            it.custom_transport_ = defaults.get("custom_transport_") or 0
        if not _to_flt(it.custom_finance_):
            it.custom_finance_ = defaults.get("custom_finance_") or 0
        if not _to_flt(it.std_margin_per):
            it.std_margin_per = defaults.get("std_margin_per") or 0
        if not _to_flt(it.custom_customs_):
            it.custom_customs_ = defaults.get("custom_customs_") or 0
        if not _to_flt(it.custom_markup_):
            it.custom_markup_ = defaults.get("custom_markup_") or 0


def run_calculation_pipeline(doc, method=None):
    """Authoritative server-side calculation — runs on every save.
    Skip on submit/cancel/amend to preserve the previewed values."""
    if doc.docstatus != 0:
        return

    # Rows added via the Items grid "Bulk Edit" CSV upload / Data Import / API
    # never fire the item_code client trigger — backfill their core fields and
    # pricing server-side before calculation (PR #13).
    backfill_item_core_fields(doc)
    backfill_item_price_defaults(doc)

    # Detect which items had their selling price manually edited.
    # Condition: custom_special_rate changed but custom_markup_ did not
    # → user typed a price directly, not a markup% change.
    # We apply the manual override LAST (after discount distribution) so
    # the user's price is truly final and not reduced by any parent discount.
    #
    # NOTE: get_doc_before_save() returns None at before_save time in this
    # Frappe version because _doc_before_save is not loaded before the hook
    # fires. Load from DB directly instead.
    prev_items = {}
    if not doc.is_new():
        try:
            db_items = frappe.get_all(
                "Quotation Item",
                filters={"parent": doc.name},
                fields=["name", "custom_special_rate", "custom_markup_"],
            )
            for pit in db_items:
                prev_items[pit.name] = pit
        except Exception:
            pass

    # Parent-level incentive as it currently stands in the DB. Needed further
    # down to tell "the user just cleared the incentive" (rows must be zeroed)
    # apart from "this quote never had a parent incentive" (item-level
    # percentages own the value and must be left untouched).
    prev_incentive_amount = 0.0
    if not doc.is_new():
        try:
            prev_incentive_amount = flt(
                frappe.db.get_value("Quotation", doc.name, "custom_incentive_amount") or 0
            )
        except Exception:
            prev_incentive_amount = 0.0

    # Capture form rate BEFORE calc_item_totals overwrites it. Used for
    # both existing-item and new-item drift detection below.
    form_rates = {it.name: flt(it.custom_special_rate) for it in doc.items}
    form_markups = {it.name: flt(it.custom_markup_) for it in doc.items}

    # Diagnostic: one compact line per item showing the exact state the
    # pipeline started from. If drift shows up in the UI after save, read
    # these lines from the bench log to see why the drift fix didn't fire.
    # Safe to leave on — prints a few lines per save and no PII.
    print(f"[Q-TRACE {doc.name}] pipeline-version=aca31a8+diag item_count={len(doc.items)}")

    manual_overrides = {}
    for it in doc.items:
        prev = prev_items.get(it.name)
        form_rate = form_rates.get(it.name, 0.0)
        form_markup = form_markups.get(it.name, 0.0)

        if prev:
            prev_rate = flt(prev.custom_special_rate)
            prev_markup = flt(prev.custom_markup_)
            if abs(form_rate - prev_rate) > 0.005:
                manual_overrides[it.name] = form_rate
                print(f"[Q-TRACE {doc.name}] idx={it.idx} user_edit db_rate={prev_rate} form_rate={form_rate} → override={form_rate}")

        calc_item_totals(it)
        calc_rate = flt(it.custom_special_rate)

        if prev and it.name not in manual_overrides:
            prev_markup = flt(prev.custom_markup_)
            db_rate = flt(prev.custom_special_rate)
            markup_delta = abs(form_markup - prev_markup)
            if markup_delta < 0.0005:
                if db_rate > 0 and abs(db_rate - calc_rate) > 1e-6:
                    manual_overrides[it.name] = db_rate
                    print(f"[Q-TRACE {doc.name}] idx={it.idx} existing_drift db_rate={db_rate} calc_rate={calc_rate} form_markup={form_markup} prev_markup={prev_markup} → override={db_rate}")
                else:
                    print(f"[Q-TRACE {doc.name}] idx={it.idx} stable db_rate={db_rate} calc_rate={calc_rate}")
            else:
                # Markup% changed — user intentionally adjusted, don't pin.
                print(f"[Q-TRACE {doc.name}] idx={it.idx} markup_changed db_rate={db_rate} form_markup={form_markup} prev_markup={prev_markup} markup_delta={markup_delta} → calc_rate={calc_rate} (no override)")

        if not prev and it.name not in manual_overrides:
            if form_rate > 0 and abs(form_rate - calc_rate) > 1e-6:
                manual_overrides[it.name] = form_rate
                print(f"[Q-TRACE {doc.name}] idx={it.idx} new_row_drift form_rate={form_rate} calc_rate={calc_rate} → override={form_rate}")
            else:
                print(f"[Q-TRACE {doc.name}] idx={it.idx} new_row_stable form_rate={form_rate} calc_rate={calc_rate}")

    # Capture pre-distribute totals needed to compute stable markup% targets.
    discount_amount = _to_flt(doc.custom_discount_amount_value)
    pre_discount_total = sum(_to_flt(it.custom_selling_price) for it in doc.items)

    # Rebase the parent's Incentive % / Amount against the CURRENT item set
    # before distributing. _finalize_submitted_quotation_save() already does
    # this for submitted quotes; the draft pipeline was the only path that
    # skipped it, so the two fields drifted apart permanently: change the items
    # (Update Items, add/remove a row, edit a special price) and the rows
    # re-derive from the percentage while custom_incentive_amount keeps the
    # figure it held for the OLD item set. Seen on QN-LTD-26-01476-1, whose
    # single row carried 11.1102% (59,328.47) while the parent amount still
    # read 47,529.60 — 8.9007% of the very same base, 24.8% apart.
    _sync_incentive_fields(doc)

    # Distribute parent-level incentive. calc_item_totals already computes
    # item-level incentive from each item's custom_incentive_ percentage; the
    # distributor overrides that with the parent-controlled amount.
    #
    # A zero amount is distributed only when the quote PREVIOUSLY had a parent
    # incentive — i.e. the user just cleared it. distribute_incentive_server()
    # is written to handle 0 by zeroing every row (it rejects negatives only),
    # but guarding on `> 0` alone left that path unreachable. And because the
    # distributor writes custom_incentive_ back onto each row, the next save
    # simply re-derived the same incentive from that stored per-item
    # percentage — so clearing the parent amount never actually removed the
    # incentive. Quotes that never had a parent incentive are left alone, which
    # keeps per-item percentages working as a way to set incentive row by row.
    incentive_amount = _to_flt(doc.custom_incentive_amount)
    if incentive_amount > 0:
        distribute_incentive_server(doc)
    elif prev_incentive_amount > 0:
        doc.custom_incentive_ = 0
        doc.custom_incentive_amount = 0
        distribute_incentive_server(doc)

    # Distribute parent-level discount only when something actually changed.
    # If no item's selling price differs from its DB value, the discount was
    # already applied in a previous save — re-running causes tiny rounding
    # drift each save (e.g. total 15,110.70 → 15,110.16 with no user edits).
    # Only redistribute when a price was manually changed this save.
    new_item_names = {it.name for it in doc.items} - set(prev_items.keys())
    if discount_amount > 0 and (manual_overrides or new_item_names):
        distribute_discount_server(doc)

    # Apply manual selling-price overrides after all automatic distributions.
    # Pass discount_total and pre_discount_total so _apply_manual_selling_rate
    # can inflate the back-solved markup% target, making the state self-consistent:
    # calc_item_totals → pre_discount_rate → distribute → user_rate on every save.
    for it in doc.items:
        manual_rate = manual_overrides.get(it.name)
        if manual_rate is not None:
            _apply_manual_selling_rate(
                it, manual_rate,
                discount_total=discount_amount,
                pre_discount_total=pre_discount_total,
            )

    rebuild_brand_summary(doc)
    recalc_doc_totals(doc)
    set_margin_flags(doc)


# ──────────────────────────────────────────────────────────────
# 5b)  PIPELINE DIAGNOSTIC  (read-only — inspect why a rate drifted)
# ──────────────────────────────────────────────────────────────
@frappe.whitelist()
def trace_quotation_calc(docname):
    """Read-only pipeline trace for diagnosing selling-rate drift.

    Loads the saved Quotation from DB, snapshots every item's current
    state, then simulates the same calculation pipeline run_calculation_pipeline
    does and records every decision point per item:

      - DB rate + markup before pipeline
      - form rate (= DB rate, since we're loading from DB here — use the
        browser console approach below to capture a real pre-save snapshot)
      - calc_item_totals output
      - drift detection outcome (manual_override? persistent? new?)
      - final rate after _apply_manual_selling_rate

    Returns a JSON-safe list. Call from the browser console with:

        frappe.call({
            method: "avientek.events.quotation.trace_quotation_calc",
            args: { docname: "QN-FZCO-26-00151" },
            callback: (r) => console.table(r.message.items)
        });

    NOTE: this is a *simulation*. It does NOT save anything. If the trace
    shows no drift but your form shows drift, the divergence is happening
    between the form-open snapshot and the save (i.e. client-side JS is
    injecting a different custom_markup_ than the DB has). Capture the
    form state in the browser console right before save to compare.
    """
    if not frappe.has_permission("Quotation", "read", doc=docname):
        frappe.throw(_("Not permitted"))

    doc = frappe.get_doc("Quotation", docname)

    # Snapshot DB state
    db_items = {}
    try:
        rows = frappe.get_all(
            "Quotation Item",
            filters={"parent": docname},
            fields=["name", "custom_special_rate", "custom_markup_", "custom_cogs"],
        )
        for r in rows:
            db_items[r.name] = r
    except Exception:
        pass

    trace = []
    for it in doc.items:
        prev = db_items.get(it.name)
        row = {
            "idx": it.idx,
            "item_code": it.item_code,
            "qty": flt(it.qty),
            "db_rate":   flt(prev.custom_special_rate) if prev else None,
            "db_markup": flt(prev.custom_markup_) if prev else None,
            "db_cogs":   flt(prev.custom_cogs) if prev else None,
            "form_rate":   flt(it.custom_special_rate),
            "form_markup": flt(it.custom_markup_),
            "form_cogs":   flt(it.custom_cogs),
            "form_sp":     flt(it.custom_special_price),
            "form_std":    flt(it.custom_standard_price_),
        }

        # Simulate calc_item_totals on a copy of the item's fields by
        # mutating a fresh child doc (not saved).
        sim = frappe.get_doc({"doctype": "Quotation Item"})
        for f in (
            "qty", "custom_standard_price_", "custom_special_price",
            "shipping_per", "custom_finance_", "custom_transport_",
            "reward_per", "custom_incentive_", "custom_customs_",
            "custom_markup_",
        ):
            setattr(sim, f, getattr(it, f, 0))
        try:
            calc_item_totals(sim)
            row["calc_rate"]   = flt(sim.custom_special_rate)
            row["calc_selling"] = flt(sim.custom_selling_price)
            row["calc_markup_value"] = flt(sim.custom_markup_value)
            row["calc_cogs"]   = flt(sim.custom_cogs)
        except Exception as e:
            row["calc_error"] = str(e)

        # Drift verdict
        drift_rate = None
        verdict = None
        if row["db_rate"] is not None and row.get("calc_rate") is not None:
            drift_rate = flt(row["calc_rate"] - row["db_rate"])
            if abs(drift_rate) <= 1e-6:
                verdict = "stable"
            elif abs(drift_rate) < 0.005:
                verdict = "sub-cent drift (truncation)"
            elif abs(drift_rate) < 0.015:
                verdict = "cent drift — investigate markup% back-solve precision"
            else:
                verdict = "substantial drift — markup% or cogs differ from prior save"
        elif row["db_rate"] is None and row.get("calc_rate") is not None:
            verdict = "new row (no DB prev)"
        row["drift_rate"] = drift_rate
        row["verdict"] = verdict
        trace.append(row)

    return {
        "docname": docname,
        "discount_amount": flt(doc.custom_discount_amount_value),
        "additional_discount_percentage": flt(doc.additional_discount_percentage),
        "item_count": len(doc.items),
        "items": trace,
    }


# ──────────────────────────────────────────────────────────────
# 6)  GET ITEM DEFAULTS  (single server call for item selection)
# ──────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_item_defaults(item_code, price_list, currency, price_list_currency, plc_conversion_rate, company=None):
    """Single whitelisted method called when item_code is selected.
    Returns all default percentages from Item Price + Brand in one response.
    Replaces the nested JS rate_calculation + update_rates calls.

    If `company` is provided, validates that an Item Price exists for that company.
    Returns `no_price_for_company=True` when no matching Item Price is found.
    """
    plc_rate = flt(plc_conversion_rate) or 1.0
    result = {}

    # 1. Item Price defaults — filter by company if provided
    ip_fields = [
        "price_list_rate",
        "custom_shipping__air_",
        "custom_shipping__sea_",
        "custom_shipping__ddu_",
        "custom_processing_",
        "custom_min_finance_charge_",
        "custom_min_margin_",
        "custom_customs_",
        "custom_markup_",
    ]

    ip = None
    if company:
        ip = frappe.db.get_value(
            "Item Price",
            {"item_code": item_code, "price_list": price_list, "custom_company": company},
            ip_fields,
            as_dict=True,
        )

    # Fallback: try without company filter if no company-specific price found
    if not ip:
        if company and frappe.db.get_single_value("Avientek Settings", "item_price_variation_in_quotation"):
            result["no_price_for_company"] = True
            result["item_code"] = item_code
            result["company"] = company
            result["price_list"] = price_list
            return result

        ip = frappe.db.get_value(
            "Item Price",
            {"item_code": item_code, "price_list": price_list},
            ip_fields,
            as_dict=True,
        )

    if ip:
        std_price = flt(ip.price_list_rate)
        # Convert if customer currency differs from price list currency
        if currency != price_list_currency:
            std_price = flt(std_price * plc_rate, 4)

        result["custom_standard_price_"] = std_price
        result["custom_special_price"]   = std_price  # default SP = standard
        result["shipping_per_air"]       = flt(ip.custom_shipping__air_)
        result["shipping_per_sea"]       = flt(ip.custom_shipping__sea_)
        result["shipping_per_ddu"]       = flt(ip.custom_shipping__ddu_)
        result["custom_transport_"]      = flt(ip.custom_processing_)
        result["custom_finance_"]        = flt(ip.custom_min_finance_charge_)
        result["std_margin_per"]         = flt(ip.custom_min_margin_)
        result["custom_customs_"]        = flt(ip.custom_customs_)
        result["custom_markup_"]         = flt(ip.custom_markup_)

    # 2. Brand defaults (fallback for fields not on Item Price)
    item_brand = frappe.db.get_value("Item", item_code, "brand")
    if item_brand:
        brand_data = frappe.db.get_value(
            "Brand", item_brand,
            ["custom_finance_", "custom_transport"],
            as_dict=True,
        )
        if brand_data:
            if not result.get("custom_finance_"):
                result["custom_finance_"] = flt(brand_data.custom_finance_)
            if not result.get("custom_transport_"):
                result["custom_transport_"] = flt(brand_data.custom_transport)

    return result


@frappe.whitelist()
def get_item_defaults_bulk(item_codes, price_list, currency, price_list_currency, plc_conversion_rate, company=None):
    """Batched version of get_item_defaults() — one round trip for many items.
    Used by the Items grid's bulk-upload auto-fetch (CSV import can add 50+
    rows at once) so the client doesn't fire one request per row. Runs a small
    fixed number of queries (Item Price + Item + Brand) instead of per item.
    Returns {item_code: {...same shape as get_item_defaults...}}.

    Note: unlike get_item_defaults(), this does not fall back to a non-company
    Item Price — but the server-side backfill_item_price_defaults() (which does
    reuse get_item_defaults with the fallback) still prices such rows on save,
    so nothing is lost. (PR #13, ported to master 2026-07-08.)"""
    item_codes = frappe.parse_json(item_codes) if isinstance(item_codes, str) else item_codes
    item_codes = list(dict.fromkeys(item_codes or []))  # de-dupe, keep order
    if not item_codes:
        return {}

    plc_rate = flt(plc_conversion_rate) or 1.0
    warn_missing_price = bool(
        company and frappe.db.get_single_value("Avientek Settings", "item_price_variation_in_quotation")
    )

    ip_filters = {"item_code": ["in", item_codes], "price_list": price_list}
    if company:
        ip_filters["custom_company"] = company

    price_by_item = {
        row.item_code: row
        for row in frappe.get_all(
            "Item Price",
            filters=ip_filters,
            fields=[
                "item_code",
                "price_list_rate",
                "custom_shipping__air_",
                "custom_shipping__sea_",
                "custom_shipping__ddu_",
                "custom_processing_",
                "custom_min_finance_charge_",
                "custom_min_margin_",
                "custom_customs_",
                "custom_markup_",
            ],
        )
    }

    item_rows = frappe.get_all(
        "Item",
        filters={"item_code": ["in", item_codes]},
        fields=["item_code", "brand", "item_name", "stock_uom", "description"],
    )
    item_by_item = {row.item_code: row for row in item_rows}
    brand_by_item = {row.item_code: row.brand for row in item_rows if row.brand}
    brands = list(set(brand_by_item.values()))
    brand_data_by_brand = {}
    if brands:
        brand_data_by_brand = {
            row.name: row
            for row in frappe.get_all(
                "Brand",
                filters={"name": ["in", brands]},
                fields=["name", "custom_finance_", "custom_transport"],
            )
        }

    result = {}
    for item_code in item_codes:
        ip = price_by_item.get(item_code)
        item = item_by_item.get(item_code)
        core_fields = {
            "item_name": item.item_name if item else None,
            "stock_uom": item.stock_uom if item else None,
            "description": item.description if item else None,
        }

        if not ip and warn_missing_price:
            result[item_code] = {
                "no_price_for_company": True,
                "item_code": item_code,
                "company": company,
                "price_list": price_list,
                **core_fields,
            }
            continue

        item_result = dict(core_fields)
        if ip:
            std_price = flt(ip.price_list_rate)
            if currency != price_list_currency:
                std_price = flt(std_price * plc_rate, 4)

            item_result["custom_standard_price_"] = std_price
            item_result["custom_special_price"]   = std_price
            item_result["shipping_per_air"]       = flt(ip.custom_shipping__air_)
            item_result["shipping_per_sea"]       = flt(ip.custom_shipping__sea_)
            item_result["shipping_per_ddu"]       = flt(ip.custom_shipping__ddu_)
            item_result["custom_transport_"]      = flt(ip.custom_processing_)
            item_result["custom_finance_"]        = flt(ip.custom_min_finance_charge_)
            item_result["std_margin_per"]         = flt(ip.custom_min_margin_)
            item_result["custom_customs_"]        = flt(ip.custom_customs_)
            item_result["custom_markup_"]         = flt(ip.custom_markup_)

        brand_data = brand_data_by_brand.get(brand_by_item.get(item_code))
        if brand_data:
            if not item_result.get("custom_finance_"):
                item_result["custom_finance_"] = flt(brand_data.custom_finance_)
            if not item_result.get("custom_transport_"):
                item_result["custom_transport_"] = flt(brand_data.custom_transport)

        result[item_code] = item_result

    return result


def calculate_additional_discount_percentage(doc, method=None):
    if not doc.discount_amount:
        return

    if not doc.apply_discount_on:
        return

    # Base amount
    base_amount = 0
    if doc.apply_discount_on == "Net Total":
        base_amount = doc.net_total
    elif doc.apply_discount_on == "Grand Total":
        base_amount = doc.grand_total

    if not base_amount:
        return

    # Convert amount → percentage
    percentage = _safe_pct(doc.discount_amount, base_amount)

    # Set percentage so core uses it
    doc.additional_discount_percentage = round(percentage, 2)

def validate_margin_approval_required(doc, method=None):
    """Block direct Submit when margin requires L1/L2 approval.

    Background: set_margin_flags (run_calculation_pipeline → 1267)
    sets `custom_auto_approve_ok=0` and `custom_level_1_approve_ok=0`
    when any brand's margin is below the per-brand threshold.

    The legacy "Quotation Final" workflow gated the Submit transition
    on `doc.custom_auto_approve_ok == 1`. The V3 seeder
    (seed_quotation_approval_v3_workflow) dropped that condition —
    QN-LTD-26-02011 (party C-AETPL-00392, -1.52% margin vs 6% std) was
    submitted on 2026-05-13 even though both approve_ok flags were 0.

    Belt-and-braces with the workflow fix
    (patches/restore_quotation_margin_gate_on_v3_workflow): the workflow
    condition hides the Submit action in the UI, but server-side
    enforcement catches API / direct-save bypass too.
    """
    if doc.docstatus != 1:
        return  # Only fires on Submit transition (Draft → Submitted)

    if cint(doc.get("custom_auto_approve_ok")):
        return  # Margin auto-approve OK — Submit is allowed

    # Approval path is intact (or already approved) — let it through
    APPROVAL_PATH_STATES = {
        # ERP-TKT-9 2026-06-05: renamed V3 state to clarify it's L1.
        # Kept old "Pending For Approval" + V2 legacy names for any
        # pre-migration rows lingering on disk.
        "Pending L1 Approval",
        "Pending For Approval",
        "Pending L2 Approval",
        "Pending Level 1 Approval",
        "Pending Level 2 Approval",
        "Approved",
        "Approved for Update",
        "Requested for update",
        "Cancellation Requested",
        "Cancellation L2 Pending",
        "Sent for Revision",
        "Cancelled",
        # Manu/Sridhar 2026-06-09 — QN-LTD-26-01884: user clicked Reject
        # on a low-margin quote and the validator (intended for direct
        # Submit) wrongly blocked the Reject workflow action because
        # "Rejected" wasn't whitelisted. Reject (and its cancel-chain
        # sibling) are explicit refusals — never need an approval gate.
        "Rejected",
        "Cancelled (Rejected)",
    }
    ws = (doc.workflow_state or "").strip()
    if ws in APPROVAL_PATH_STATES:
        return

    # Direct Submit attempt on a low-margin quote
    need_l2 = not cint(doc.get("custom_level_1_approve_ok"))
    level = "Level 2" if need_l2 else "Level 1"
    frappe.throw(
        _(
            "This Quotation cannot be submitted directly — margin requires "
            "{0} approval. Please use 'Send for Approval' instead of 'Submit'."
        ).format(level),
        title=_("Approval Required"),
    )


def validate_total_discount(doc, method):
    """Ensure sum of child discounts matches parent discount amount.
    Only validate when a discount is actually set (> 0).
    """
    parent_discount = _to_flt(doc.custom_discount_amount_value)
    if parent_discount <= 0:
        return

    total_row_discount = sum(_to_flt(row.custom_discount_amount_qty) for row in doc.items)

    if round(total_row_discount, 2) != round(parent_discount, 2):
        frappe.throw("Sum of item discount amounts must equal parent discount amount")


# Sridhar 2026-06-05: removed copy_first_item_part_number. The parent-level
# Quotation.first_item_part_number / .optional_item_part_numbers mirror
# fields are removed (patch drop_quotation_part_number_mirror_fields)
# because the Optional Item child table is now its own DocType (Step 4 of
# the Optional Item migration). Report View can show per-table Part
# Number columns directly without the collision the mirrors worked around.


def sync_workflow_status(doc, method=None):
    """Keep workflow_status mirror in sync with workflow_state.

    Sridhar/Rahul 2026-06-02: workflow_status was created as a Custom Field
    with fetch_from="workflow_state" so it would surface in the list-view
    filter typeahead (Frappe v15 hides the auto-injected workflow_state
    Link). But fetch_from="workflow_state" is NOT a valid Frappe path
    (fetch_from needs a Link.targetfield chain like "customer.tax_id"),
    so the mirror only got populated via incidental save events. Workflow
    transitions that write workflow_state via frappe.db.set_value bypassed
    fetch_from entirely, leaving workflow_status stuck at stale values
    (e.g. quote moved Pending For Approval -> Approved but filter still
    counted it as Pending For Approval).

    Sridhar ERP-TKT-7 2026-06-05: the hook was wired ONLY on `validate`
    initially. That missed two real paths in prod that produced 21 drift
    rows in 24h after the 2026-06-02 deploy:
      - Cancel transitions (docstatus 1→2): doc.cancel() does NOT fire
        validate in Frappe v15, only on_cancel. So Cancellation chain
        endings left workflow_status stale at "Cancellation Requested".
      - on_update_after_submit transitions (docstatus 1→1 between
        Approved/Rejected/Pending L2 Approval): in some flows the
        workflow apply uses direct db.set_value bypassing validate.

    Now wired on validate + on_update_after_submit + on_cancel. The
    function is idempotent (only writes when values differ) so multiple
    events on the same save are harmless.

    For docstatus=2 cancel path: doc.workflow_status assignment alone
    doesn't persist (the row is being cancelled, no .save call follows).
    For that case the function ALSO writes directly to DB via
    frappe.db.set_value when method == "on_cancel".
    """
    current_state = doc.get("workflow_state") or ""
    current_status = doc.get("workflow_status") or ""
    if current_state == current_status:
        return
    # In-memory update (caught by the subsequent save/submit write)
    doc.workflow_status = current_state
    # on_cancel runs after the cancel has already been written, so a
    # plain field assignment doesn't persist. Force a direct DB write
    # for the cancel path. Same fallback for on_update_after_submit
    # paths that don't trigger a full save afterwards.
    if method in ("on_cancel", "on_update_after_submit"):
        try:
            frappe.db.set_value(
                "Quotation", doc.name, "workflow_status", current_state,
                update_modified=False,
            )
        except Exception:
            # Don't let a sync failure block the workflow transition.
            pass


def get_overall_margin(salesperson, brand):
    if not (salesperson and brand):
        return 0

    date_cut = frappe.db.get_single_value(
        "Selling Settings", "custom_applicable_date"
    )
    include_cancelled = cint(frappe.db.get_single_value(
        "Selling Settings", "custom_include_cancelled_quotations"
    ))
    include_lost = cint(frappe.db.get_single_value(
        "Selling Settings", "custom_include_lost_quotations"
    ))

    # Build docstatus / status filter
    status_parts = ["q.docstatus = 1"]
    if include_cancelled:
        status_parts.append("q.docstatus = 2")
    if include_lost:
        status_parts.append("q.status = 'Lost'")

    status_cond = "(" + " OR ".join(status_parts) + ")"

    cond = f"""
        {status_cond}
        AND q.sales_person = %(sp)s
        AND qi.brand = %(br)s
        AND qi.rate > 0
    """

    if date_cut:
        cond += " AND q.transaction_date >= %(dc)s"

    rows = frappe.db.sql(
        f"""
        SELECT qi.rate, qi.custom_cogs, qi.qty
        FROM `tabQuotation` q
        JOIN `tabQuotation Item` qi ON qi.parent = q.name
        WHERE {cond}
        """,
        {"sp": salesperson, "br": brand, "dc": date_cut},
        as_dict=True,
    )

    if not rows:
        return 0

    margins = []
    for r in rows:
        cogs_per_unit = flt(r.custom_cogs) / flt(r.qty or 1)
        # rate was divided by unguarded: a free-of-charge historical line
        # (rate = 0) raised ZeroDivisionError and took down the whole
        # margin-approval evaluation for the quote.
        margin = _safe_pct(flt(r.rate) - cogs_per_unit, r.rate)
        margins.append(margin)

    overall_margin = sum(margins) / len(margins)
    return overall_margin


def set_margin_flags(doc, method=None):
    """Evaluate margin approval rules per brand from Brand Summary.

    Decision flow (worst case wins across all brands):
    1. New Margin >= Standard Margin OR >= 80% of Std → APPROVED
    2. New Margin >= 60% of Std AND Overall Margin >= 80% of Std → APPROVED_WITH_WARNING
    3. New Margin >= 60% of Std AND Overall Margin < 80% of Std → LEVEL_1
    4. New Margin < 60% of Std → LEVEL_2 (mandatory note)
    """
    doc.custom_auto_approve_ok = 1
    doc.custom_level_1_approve_ok = 1

    salesperson = doc.get("sales_person") or ""
    level_1_required = False
    level_2_required = False
    warnings = []

    for bs_row in (doc.get("custom_quotation_brand_summary") or []):
        brand = bs_row.brand or ""
        new_margin = flt(bs_row.margin_percent)
        std_margin = flt(bs_row.std_margin_percent)
        abs_margin = flt(bs_row.margin)
        total_selling = flt(bs_row.total_selling)
        total_cost = flt(bs_row.total_cost)

        # Hard sanity gate (Rahul / Jithin 2026-05-22 — QN-KSA-26-00132).
        # Pre-fix, a brand with no `std_margin_percent` configured fell
        # through `if not std_margin: APPROVED` even when the ABSOLUTE
        # margin was negative (selling < cost) — auto-approving a
        # SAR 21,451.50 loss-making quote. Two absolute checks now run
        # BEFORE any std-margin / percent logic and force LEVEL_2
        # regardless of the brand's configured threshold:
        #   (a) margin < 0  → selling price below cost (guaranteed loss)
        #   (b) total_selling == 0 with total_cost > 0 → degenerate
        #       quote (the percent calc divides by zero and surfaces
        #       margin_percent=0, hiding the loss)
        if abs_margin < 0:
            bs_row.approval_status = "LEVEL_2"
            level_2_required = True
            warnings.append(
                _("Brand <b>{0}</b>: ABSOLUTE margin is <b>{1}</b> (negative — "
                  "selling below cost). Level 2 approval mandatory.").format(
                    brand, round(abs_margin, 2)
                )
            )
            continue
        if total_selling <= 0 and total_cost > 0:
            bs_row.approval_status = "LEVEL_2"
            level_2_required = True
            warnings.append(
                _("Brand <b>{0}</b>: Total Selling is <b>{1}</b> but Total Cost "
                  "is <b>{2}</b> — degenerate quotation. Level 2 approval mandatory.").format(
                    brand, round(total_selling, 2), round(total_cost, 2)
                )
            )
            continue

        # Skip brands with no standard margin (no restriction).
        # Reached only when the absolute checks above passed, so the
        # margin is guaranteed non-negative.
        if not std_margin:
            bs_row.approval_status = "APPROVED"
            continue

        # Rule 1: Auto Approval
        if new_margin >= std_margin or new_margin >= (0.80 * std_margin):
            bs_row.approval_status = "APPROVED"
            continue

        # Rule 2 & 3: 60-80% range — check historical overall margin
        if new_margin >= (0.60 * std_margin):
            overall = get_overall_margin(salesperson, brand)
            if overall >= (0.80 * std_margin):
                bs_row.approval_status = "APPROVED_WITH_WARNING"
                warnings.append(
                    _("Brand <b>{0}</b>: Current margin {1}% below standard {2}%, "
                      "but historical overall margin ({3}%) is healthy.").format(
                        brand, round(new_margin, 2), round(std_margin, 2), round(overall, 2)
                    )
                )
                continue
            else:
                bs_row.approval_status = "LEVEL_1"
                level_1_required = True
                # #0502 (Rahul/Orders.Mea 2026-08-18): the L1 branch was the
                # ONLY decision path that emitted no warning, so a quote routed
                # to L1 gave the user no reason ("went for approval, no warning").
                # Explain exactly why: this brand is in the 60-80%-of-standard
                # band and the salesperson's historical overall margin isn't
                # high enough to auto-approve it.
                warnings.append(
                    _("Brand <b>{0}</b>: current margin {1}% is below 80% of standard "
                      "{2}% (needs {3}%), and historical overall margin ({4}%) is not "
                      "high enough — Level 1 approval required.").format(
                        brand, round(new_margin, 2), round(std_margin, 2),
                        round(0.80 * std_margin, 2), round(overall, 2)
                    )
                )
                continue

        # Rule 4: Critical — below 60%
        bs_row.approval_status = "LEVEL_2"
        level_2_required = True

    # Additional Level 2 triggers (probability-based — Finance Manager request):
    #   A. Probability drops below 75% (from any higher value) → LEVEL_2
    #   B. Probability stays at 75% but Expected Closing Date *month* changes → LEVEL_2
    prob_reason = _probability_change_requires_level_2(doc)
    if prob_reason:
        level_2_required = True
        warnings.append(_("Level 2 approval required: {0}").format(prob_reason))

    # ERP-TKT-2 (Sridhar/Rahul 2026-06-05, Option A confirmed):
    # Incentive applied → force Level 2 regardless of margin.
    # Pre-fix, set_margin_flags only inspected margin% / probability —
    # never the three incentive fields — so a healthy-margin quote
    # with a large incentive auto-approved silently, bypassing both
    # L1 and L2. Now: any of `custom_apply_incentive`,
    # `custom_incentive_amount > 0`, or any item with
    # `custom_incentive_ > 0` routes to L2.
    incentive_reason = _incentive_applied_reason(doc)
    if incentive_reason:
        level_2_required = True
        warnings.append(_("Level 2 approval required: {0}").format(incentive_reason))

    # Worst case wins
    if level_2_required:
        doc.custom_auto_approve_ok = 0
        doc.custom_level_1_approve_ok = 0
    elif level_1_required:
        doc.custom_auto_approve_ok = 0
        doc.custom_level_1_approve_ok = 1

    # Show warnings (non-blocking) — use multiple methods for visibility
    if warnings:
        msg = "<br><br>".join(warnings)
        frappe.msgprint(msg, title=_("Margin Warning"), indicator="orange", alert=True)


def _incentive_applied_reason(doc):
    """Detect ANY incentive applied on the quotation.

    Returns a human-readable reason string if incentive is applied,
    else None. Caller (set_margin_flags) forces Level 2 approval when
    a reason is returned.

    Sridhar/Rahul 2026-06-05 — Option A confirmed for ERP-TKT-2.

    Three USER-INPUT avenues are checked. Any one triggers L2:
      1. Parent `custom_incentive_` > 0     (parent-level percentage)
      2. Parent `custom_incentive_amount` > 0  (parent-level lump-sum)
      3. Any items[*].custom_incentive_ > 0    (per-item percentage)

    Note: `custom_apply_incentive` is a BUTTON field (action trigger,
    no stored value) — cannot be inspected. `custom_total_incentive_new`
    is a calculated field populated by distribute_incentive_server()
    which runs AFTER set_margin_flags in run_calculation_pipeline,
    so it's not reliable at routing time either. Only the three
    user-input avenues above are checked.

    flt() is used so blank/null resolves to 0 without raising. The
    `> 0` comparison ignores negative incentives if anyone ever uses
    them — incentive is defined as a positive concession to the
    customer.
    """
    parent_pct = flt(doc.get("custom_incentive_"))
    if parent_pct > 0:
        return _("Parent-level incentive percent {0}% applied.").format(parent_pct)
    parent_amt = flt(doc.get("custom_incentive_amount"))
    if parent_amt > 0:
        return _("Parent-level incentive amount {0} applied.").format(parent_amt)
    item_count = 0
    for it in (doc.get("items") or []):
        if flt(it.get("custom_incentive_")) > 0:
            item_count += 1
    if item_count:
        return _("Per-item incentive applied on {0} row(s).").format(item_count)
    return None


def _probability_change_requires_level_2(doc):
    """Detect probability-based Level 2 triggers.

    Returns a human-readable reason string if a trigger fires, else None.

    Trigger A — any change that *lands below* 75%
        If the new probability is < 75% and it changed from whatever it was
        before, Level 2 approval is needed. Catches 100% → 50%, 75% → 10%,
        etc. An already-below-75% save that doesn't change the value is not
        a trigger (prevents every subsequent save from re-prompting).

    Trigger B — closing-date *month* change while at 75%
        If the probability was 75% before and still is, but the
        Expected Closing Date moved to a different calendar month, that's
        a schedule slip worth reviewing at Level 2.
    """
    if doc.is_new():
        return None

    old_prob = None
    old_ecd = None
    before = None
    try:
        before = doc.get_doc_before_save()
    except Exception:
        before = None

    if before:
        old_prob = before.get("probabilities") or ""
        old_ecd = before.get("expected_closing_dates")
    else:
        row = frappe.db.get_value(
            "Quotation", doc.name,
            ["probabilities", "expected_closing_dates"], as_dict=True,
        )
        if not row:
            return None
        old_prob = row.get("probabilities") or ""
        old_ecd = row.get("expected_closing_dates")

    new_prob = doc.get("probabilities") or ""
    new_ecd = doc.get("expected_closing_dates")

    def _pct(v):
        try:
            return int(str(v or "").rstrip("%").strip() or 0)
        except (ValueError, TypeError):
            return 0

    op, np = _pct(old_prob), _pct(new_prob)

    # Trigger A
    if np < 75 and np != op:
        return _("Probability changed from {0} to {1}").format(old_prob or "-", new_prob or "-")

    # Trigger B
    if op == 75 and np == 75 and old_ecd and new_ecd:
        if str(old_ecd)[:7] != str(new_ecd)[:7]:
            return _("Expected Closing Date month changed from {0} to {1} at 75% probability").format(
                old_ecd, new_ecd
            )

    return None


def _pct_int(v):
    """Parse '75%' / '75' / None into int."""
    try:
        return int(str(v or "").rstrip("%").strip() or 0)
    except (ValueError, TypeError):
        return 0


def capture_submitted_probability(doc, method=None):
    """Sridhar 2026-05-28: freeze the probability value at submit time
    into `submitted_probability` so the post-submit approval popup has
    a stable baseline for the entire life of the doc — not just the
    last saved value (which drifts after each downgrade).

    Runs on Quotation.on_submit. Idempotent — only writes if currently
    empty (re-submits from Cancel+Amend will be handled by the new
    amendment's own on_submit).
    """
    if doc.get("submitted_probability"):
        return
    current = doc.get("probabilities") or ""
    if not current:
        return
    doc.db_set("submitted_probability", current, update_modified=False)


def validate_probability_change_approval(doc, method=None):
    """Sridhar 2026-05-27/28 (Probability BRD, Jithin/FM approved):
    enforce that a probability downgrade on a submitted Quotation
    captures a mandatory reason. The reason is set by the JS popup
    in public/js/quotation.js BEFORE saving. If the user bypasses
    the UI (direct API call, server script, etc.) and saves without
    setting probability_change_reason, this throws.

    Trigger uses the FROZEN `submitted_probability` as baseline
    (per BRD: "original probability at the time of submission" is
    the eternal baseline). Sridhar 2026-05-28 bug fix: previous
    version compared against last-saved value which let post-refresh
    edits slip through after the first downgrade.

        - If submitted_probability >= 75% AND new value < 75% AND
          value actually changed → require reason.
        - If submitted_probability < 75% → all post-submit edits free.

    On a triggering save WITH reason set: writes an audit Comment
    capturing old → new + reason + user, then clears the reason field
    so the NEXT change requires a fresh reason.
    """
    if doc.is_new() or doc.docstatus != 1:
        return

    submitted = doc.get("submitted_probability") or ""
    if not submitted:
        # Legacy doc with no captured submission value — fall back to
        # the per-save delta logic (won't catch refresh-then-edit cases
        # but preserves existing behaviour for old data).
        trigger_reason = _probability_change_requires_level_2(doc)
        if not trigger_reason:
            return
    else:
        submitted_pct = _pct_int(submitted)
        if submitted_pct < 75:
            # Originally low-prob deal — all edits are free per BRD.
            return
        new_pct = _pct_int(doc.get("probabilities") or "")
        if new_pct >= 75:
            # New value still in high range — also free per BRD.
            return
        # Check value actually changed from current saved (cheap dirty check)
        try:
            before = doc.get_doc_before_save()
        except Exception:
            before = None
        if before and (before.get("probabilities") or "") == (doc.get("probabilities") or ""):
            # No change on this save (e.g., status-only update) — don't fire.
            return
        trigger_reason = _("Probability downgraded from submitted value {0} to {1}").format(
            submitted, doc.get("probabilities") or ""
        )

    change_reason = (doc.get("probability_change_reason") or "").strip()
    if not change_reason:
        frappe.throw(
            _(
                "Lowering probability requires management approval. "
                "Please use the popup that appears when you change the "
                "Probability field — fill in 'Reason for Change' and "
                "click 'Send for Approval'. ({0})"
            ).format(trigger_reason),
            title=_("Reason Required"),
        )

    # Sridhar 2026-05-29: prior version wrote Comment + cleared field via
    # doc-mutation in validate. Trace on QN-LTD-26-02120 showed neither
    # happened — likely the workflow action save path bypassed our hooks
    # OR the Comment insert errored silently. Both steps now hardened:
    #   1. Comment insert wrapped in try/except so failure doesn't block save
    #   2. Field cleared via frappe.db.set_value (bypasses validate cycle,
    #      survives even if doc.save() path is unusual)
    #   3. Errors logged via frappe.log_error for diagnosis
    from frappe.utils import now_datetime, escape_html

    try:
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "Quotation",
            "reference_name": doc.name,
            "content": _(
                "<b>Probability change request</b> by {0} at {1}.<br>"
                "<b>Change:</b> {2}<br>"
                "<b>Reason:</b> {3}"
            ).format(
                frappe.session.user,
                now_datetime().strftime("%Y-%m-%d %H:%M"),
                escape_html(trigger_reason),
                escape_html(change_reason).replace("\n", "<br>"),
            ),
        }).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(
            message=f"Probability change Comment failed for {doc.name}: {e}",
            title="prob_change Comment",
        )

    # Clear the reason field one-shot — use db_set so the change persists
    # even on save paths that skip the doc-mutation persistence. Also
    # update the in-memory doc so subsequent hooks see the cleared value.
    try:
        frappe.db.set_value(
            "Quotation", doc.name, "probability_change_reason", "",
            update_modified=False,
        )
        doc.probability_change_reason = ""
    except Exception as e:
        frappe.log_error(
            message=f"Probability reason clear failed for {doc.name}: {e}",
            title="prob_change reason clear",
        )


def _get_probability_revision_approver_roles():
    """Return the configured list of roles allowed to approve / reject
    pending probability changes.

    Sridhar 2026-05-29 (round 2): use the dedicated
    `probability_approver_roles` field on Avientek Settings. Falls back
    to `quote_l2_approver_roles` if the dedicated field is empty, then
    to empty list (caller defaults to System Manager only).
    """
    try:
        settings = frappe.get_single("Avientek Settings")
    except Exception:
        return []
    roles = [r.role for r in (settings.get("probability_approver_roles") or []) if r.get("role")]
    if roles:
        return roles
    return [r.role for r in (settings.get("quote_l2_approver_roles") or []) if r.get("role")]


def _emails_enabled():
    try:
        return bool(frappe.db.get_single_value(
            "Avientek Settings", "enable_probability_change_emails"
        ))
    except Exception:
        return False


def _user_can_approve_probability(user=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    user_roles = set(frappe.get_roles(user))
    approver_roles = set(_get_probability_revision_approver_roles())
    if not approver_roles:
        # Fallback to System Manager when not configured (admin only)
        return "System Manager" in user_roles
    return bool(user_roles & approver_roles)


@frappe.whitelist()
def submit_probability_change(quotation_name, new_probability, reason):
    """Sridhar 2026-05-29 (BRD-faithful): capture a pending probability
    change request without modifying the actual `probabilities` field.
    The probability field stays at its current (high) value — only the
    pending_probability_* fields are populated. The L2 approver then
    decides via approve_probability_change / reject_probability_change.

    Trigger conditions:
      submitted_probability >= 75% AND new_probability < 75%
    """
    if not quotation_name:
        frappe.throw(_("Quotation name is required."))
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Reason is required."))

    row = frappe.db.get_value(
        "Quotation", quotation_name,
        ["docstatus", "submitted_probability", "probabilities",
         "pending_probability_status"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Quotation {0} not found.").format(quotation_name))
    if row.docstatus != 1:
        frappe.throw(_("Quote must be submitted to request a probability change."))

    if row.pending_probability_status == "Pending":
        frappe.throw(
            _("This Quotation already has a Pending probability change. "
              "Wait for the approver to act on it before requesting another.")
        )

    submitted = (row.submitted_probability or "").strip()
    if not submitted:
        frappe.throw(_("No submitted_probability captured on this quote — cannot validate change."))

    submitted_pct = _pct_int(submitted)
    new_pct = _pct_int(new_probability)

    if submitted_pct < 75 or new_pct >= 75:
        # No approval needed per BRD — update directly and skip the
        # pending-request flow.
        frappe.db.set_value(
            "Quotation", quotation_name, "probabilities", new_probability,
            update_modified=True,
        )
        frappe.db.commit()
        return {"ok": True, "no_approval_needed": True}

    # Real downgrade — capture as pending request. probability field
    # stays at its current high value (BRD: "field should visually
    # revert to its previous high value until approval is granted").
    from frappe.utils import now_datetime, escape_html

    frappe.db.set_value(
        "Quotation", quotation_name,
        {
            "pending_probability_value": new_probability,
            "pending_probability_status": "Pending",
            "pending_probability_reason": reason,
            "pending_probability_requested_by": frappe.session.user,
            "pending_probability_requested_at": now_datetime(),
        },
        update_modified=True,
    )

    try:
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "Quotation",
            "reference_name": quotation_name,
            "content": _(
                "<b>Probability change requested</b> by {0} at {1}.<br>"
                "<b>Requested:</b> {2} → {3}<br>"
                "<b>Reason:</b> {4}<br>"
                "<i>Awaiting L2 approver.</i>"
            ).format(
                frappe.session.user,
                now_datetime().strftime("%Y-%m-%d %H:%M"),
                escape_html(submitted),
                escape_html(new_probability),
                escape_html(reason).replace("\n", "<br>"),
            ),
        }).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(
            message=f"submit_probability_change Comment failed for {quotation_name}: {e}",
            title="submit_prob_change Comment",
        )

    # Send ToDo + email to all L2 approvers
    try:
        _notify_probability_approvers(quotation_name, submitted, new_probability, reason)
    except Exception as e:
        frappe.log_error(
            message=f"notify approvers failed for {quotation_name}: {e}",
            title="submit_prob_change notify",
        )

    frappe.db.commit()
    return {"ok": True, "pending": True}


def _notify_probability_approvers(quotation_name, old_val, new_val, reason):
    approver_roles = _get_probability_revision_approver_roles()
    if not approver_roles:
        return

    users = frappe.db.sql(
        """SELECT DISTINCT u.name, u.email
           FROM `tabUser` u
           INNER JOIN `tabHas Role` hr ON hr.parent = u.name
           WHERE hr.role IN %(roles)s
             AND u.enabled = 1
             AND u.name NOT IN ('Administrator', 'Guest')""",
        {"roles": tuple(approver_roles)},
        as_dict=True,
    )

    todo_desc = _(
        "Probability change requested on {0}: {1} → {2}. Reason: {3}"
    ).format(quotation_name, old_val, new_val, reason)

    requester = frappe.session.user
    for u in users:
        try:
            frappe.get_doc({
                "doctype": "ToDo",
                "allocated_to": u["name"],
                "reference_type": "Quotation",
                "reference_name": quotation_name,
                "description": todo_desc,
                "priority": "High",
                "status": "Open",
            }).insert(ignore_permissions=True)
        except Exception:
            pass

    if not _emails_enabled():
        return

    recipients = [u["email"] for u in users if u.get("email")]
    if not recipients:
        return

    try:
        site_url = frappe.utils.get_url()
        subject = _("Probability change approval needed — {0}").format(quotation_name)
        body = _(
            "<p>Hi,</p>"
            "<p>A probability change request needs your review on Quotation "
            "<a href=\"{site}/app/quotation/{quote}\"><b>{quote}</b></a>.</p>"
            "<p><b>Requested by:</b> {by}<br>"
            "<b>Change:</b> {old} → {new}<br>"
            "<b>Reason:</b> {reason}</p>"
            "<p>Open the quote and click <b>Probability → Approve</b> or "
            "<b>Probability → Reject</b> to act on this request.</p>"
        ).format(
            site=site_url, quote=quotation_name, by=requester,
            old=frappe.utils.escape_html(old_val),
            new=frappe.utils.escape_html(new_val),
            reason=frappe.utils.escape_html(reason).replace("\n", "<br>"),
        )
        frappe.sendmail(
            recipients=recipients, subject=subject, message=body,
            reference_doctype="Quotation", reference_name=quotation_name,
            now=True,
        )
    except Exception as e:
        frappe.log_error(
            message=f"prob change request email failed for {quotation_name}: {e}",
            title="prob_change request email",
        )


def _email_requester_decision(quotation_name, decision, old_val, new_val, requester, extra=""):
    """decision: 'approved' or 'rejected'."""
    if not _emails_enabled():
        return
    if not requester:
        return
    email = frappe.db.get_value("User", requester, "email") or requester
    if not email:
        return

    site_url = frappe.utils.get_url()
    if decision == "approved":
        subject = _("Probability change APPROVED — {0}").format(quotation_name)
        body = _(
            "<p>Hi,</p>"
            "<p>Your probability change request on Quotation "
            "<a href=\"{site}/app/quotation/{quote}\"><b>{quote}</b></a> "
            "has been <b style=\"color:#28a745\">APPROVED</b>.</p>"
            "<p>The Quotation probability is now <b>{new}</b> (was <b>{old}</b>).</p>"
            "<p>Approved by: {actor} at {ts}.</p>"
        ).format(
            site=site_url, quote=quotation_name,
            old=frappe.utils.escape_html(old_val),
            new=frappe.utils.escape_html(new_val),
            actor=frappe.session.user,
            ts=frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M"),
        )
    else:
        subject = _("Probability change REJECTED — {0}").format(quotation_name)
        body = _(
            "<p>Hi,</p>"
            "<p>Your probability change request on Quotation "
            "<a href=\"{site}/app/quotation/{quote}\"><b>{quote}</b></a> "
            "has been <b style=\"color:#dc3545\">REJECTED</b>.</p>"
            "<p>The probability stays at <b>{old}</b>; your requested value <b>{new}</b> "
            "will NOT be applied.</p>"
            "<p>Rejection reason:<br>{extra}</p>"
            "<p>Rejected by: {actor} at {ts}.</p>"
        ).format(
            site=site_url, quote=quotation_name,
            old=frappe.utils.escape_html(old_val),
            new=frappe.utils.escape_html(new_val),
            extra=frappe.utils.escape_html(extra).replace("\n", "<br>"),
            actor=frappe.session.user,
            ts=frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M"),
        )

    try:
        frappe.sendmail(
            recipients=[email], subject=subject, message=body,
            reference_doctype="Quotation", reference_name=quotation_name,
            now=True,
        )
    except Exception as e:
        frappe.log_error(
            message=f"prob change decision email failed for {quotation_name}: {e}",
            title="prob_change decision email",
        )


@frappe.whitelist()
def approve_probability_change(quotation_name):
    """Approve a pending probability change. probabilities = pending_value,
    pending fields cleared, audit Comment written. Caller must hold a
    role from `quote_l2_approver_roles` (or be Administrator).
    """
    if not quotation_name:
        frappe.throw(_("Quotation name is required."))

    if not _user_can_approve_probability():
        frappe.throw(_("You do not have permission to approve probability changes."))

    row = frappe.db.get_value(
        "Quotation", quotation_name,
        ["pending_probability_value", "pending_probability_status",
         "pending_probability_reason", "pending_probability_requested_by",
         "probabilities"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Quotation {0} not found.").format(quotation_name))
    if row.pending_probability_status != "Pending":
        frappe.throw(_("No pending probability change to approve."))

    new_val = row.pending_probability_value
    old_val = row.probabilities

    from frappe.utils import now_datetime, escape_html

    frappe.db.set_value(
        "Quotation", quotation_name,
        {
            "probabilities": new_val,
            "pending_probability_status": "Approved",
            # Keep the requested-by + at + reason fields populated as audit
            # record. The status flip is enough to identify resolved.
        },
        update_modified=True,
    )

    # Reset pending fields (status stays "Approved" briefly for audit;
    # clear the request body so it doesn't show as a stale banner)
    frappe.db.set_value(
        "Quotation", quotation_name,
        {
            "pending_probability_value": "",
            "pending_probability_reason": "",
            "pending_probability_requested_by": "",
        },
        update_modified=False,
    )

    frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Info",
        "reference_doctype": "Quotation",
        "reference_name": quotation_name,
        "content": _(
            "<b>Probability change APPROVED</b> by {0} at {1}.<br>"
            "<b>Changed:</b> {2} → {3}<br>"
            "<b>Originally requested by:</b> {4}"
        ).format(
            frappe.session.user,
            now_datetime().strftime("%Y-%m-%d %H:%M"),
            escape_html(old_val or ""),
            escape_html(new_val or ""),
            escape_html(row.pending_probability_requested_by or "(unknown)"),
        ),
    }).insert(ignore_permissions=True)

    # Close any open ToDos against this Quotation for probability requests
    try:
        frappe.db.sql(
            """UPDATE `tabToDo` SET status='Closed'
               WHERE reference_type='Quotation'
                 AND reference_name=%s
                 AND status='Open'
                 AND description LIKE %%s""",
            (quotation_name, "%Probability change requested%"),
        )
    except Exception:
        pass

    # Email the original requester about the decision
    try:
        _email_requester_decision(
            quotation_name, "approved",
            old_val=old_val, new_val=new_val,
            requester=row.pending_probability_requested_by,
        )
    except Exception:
        pass

    frappe.db.commit()
    return {"ok": True, "approved": True, "new_value": new_val}


@frappe.whitelist()
def reject_probability_change(quotation_name, rejection_reason=""):
    """Reject a pending probability change. Pending fields cleared,
    probabilities stays at current value, audit Comment written.
    """
    if not quotation_name:
        frappe.throw(_("Quotation name is required."))

    if not _user_can_approve_probability():
        frappe.throw(_("You do not have permission to reject probability changes."))

    rejection_reason = (rejection_reason or "").strip()
    if not rejection_reason:
        frappe.throw(_("Rejection reason is required."))

    row = frappe.db.get_value(
        "Quotation", quotation_name,
        ["pending_probability_value", "pending_probability_status",
         "pending_probability_reason", "pending_probability_requested_by",
         "probabilities"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Quotation {0} not found.").format(quotation_name))
    if row.pending_probability_status != "Pending":
        frappe.throw(_("No pending probability change to reject."))

    from frappe.utils import now_datetime, escape_html

    frappe.db.set_value(
        "Quotation", quotation_name,
        {
            "pending_probability_status": "Rejected",
            "pending_probability_value": "",
            "pending_probability_reason": "",
            "pending_probability_requested_by": "",
        },
        update_modified=True,
    )

    frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Info",
        "reference_doctype": "Quotation",
        "reference_name": quotation_name,
        "content": _(
            "<b>Probability change REJECTED</b> by {0} at {1}.<br>"
            "<b>Rejected request:</b> {2} → {3}<br>"
            "<b>Rejection reason:</b> {4}<br>"
            "<b>Originally requested by:</b> {5}"
        ).format(
            frappe.session.user,
            now_datetime().strftime("%Y-%m-%d %H:%M"),
            escape_html(row.probabilities or ""),
            escape_html(row.pending_probability_value or ""),
            escape_html(rejection_reason).replace("\n", "<br>"),
            escape_html(row.pending_probability_requested_by or "(unknown)"),
        ),
    }).insert(ignore_permissions=True)

    try:
        frappe.db.sql(
            """UPDATE `tabToDo` SET status='Closed'
               WHERE reference_type='Quotation'
                 AND reference_name=%s
                 AND status='Open'
                 AND description LIKE %%s""",
            (quotation_name, "%Probability change requested%"),
        )
    except Exception:
        pass

    # Email the original requester about the rejection
    try:
        _email_requester_decision(
            quotation_name, "rejected",
            old_val=row.probabilities,
            new_val=row.pending_probability_value,
            requester=row.pending_probability_requested_by,
            extra=rejection_reason,
        )
    except Exception:
        pass

    frappe.db.commit()
    return {"ok": True, "rejected": True}


@frappe.whitelist()
def can_approve_probability_change(quotation_name=None):
    """Cheap helper for the JS to ask whether the current user can show
    the Approve / Reject buttons. Returns boolean.
    """
    return _user_can_approve_probability()


@frappe.whitelist()
def update_special_price(quotation_name, items):
    """Update Special Price on a submitted Quotation.
    Recalculates COGS and margin but keeps Selling Price / Rate / Amount unchanged."""
    items = frappe.parse_json(items)
    doc = frappe.get_doc("Quotation", quotation_name)

    if doc.docstatus != 1:
        frappe.throw("This action is only allowed on submitted Quotations.")

    for item_update in items:
        row_name = item_update.get("name")
        if not row_name:
            continue

        # Load the current row values
        row = None
        for r in doc.items:
            if r.name == row_name:
                row = r
                break
        if not row:
            continue

        new_sp = flt(item_update.get("custom_special_price"))
        note = item_update.get("custom_special_price_note") or ""
        qty = max(cint(row.qty), 1)
        std_price = _to_flt(row.custom_standard_price_)

        # Recalculate cost components with new SP
        shipping  = flt(_to_flt(row.shipping_per)      * std_price / 100 * qty, 4)
        finance   = flt(_to_flt(row.custom_finance_)   * new_sp    / 100 * qty, 4)
        transport = flt(_to_flt(row.custom_transport_)  * std_price / 100 * qty, 4)
        reward    = flt(_to_flt(row.reward_per)         * new_sp    / 100 * qty, 4)

        base_amt = flt(new_sp * qty + shipping + finance + transport + reward, 4)

        incentive = flt(_to_flt(row.custom_incentive_) * new_sp * qty / 100, 4)

        cogs_before_customs = flt(base_amt + incentive, 4)
        customs = flt(_to_flt(row.custom_customs_) * cogs_before_customs / 100, 4)

        cogs = flt(cogs_before_customs + customs, 4)

        markup = flt(_to_flt(row.custom_markup_) * cogs / 100, 4)

        # Keep existing selling price unchanged
        selling = flt(row.custom_selling_price)

        # Recalculate margin based on existing selling vs new cogs
        margin_val = flt(selling - cogs, 4)
        margin_pct = _safe_pct(margin_val, selling)

        frappe.db.set_value("Quotation Item", row_name, {
            "custom_special_price": new_sp,
            "custom_special_price_note": note,
            "shipping": shipping,
            "custom_finance_value": finance,
            "custom_transport_value": transport,
            "reward": reward,
            "custom_incentive_value": incentive,
            "custom_customs_value": customs,
            "custom_markup_value": markup,
            "custom_cogs": cogs,
            "custom_margin_": margin_pct,
            "custom_margin_value": margin_val,
        }, update_modified=True)

    # Jithin 2026-05-15 — also refresh the doc-level totals (Total Margin
    # Percent, Total Margin, Total Cost, Total Selling, …) AND the
    # Brand Summary child table. Without this, item rows updated above
    # but the parent display + Brand Summary still showed pre-edit
    # values until the user manually re-saved the doc.
    frappe.db.commit()  # flush item-row changes so doc.reload() sees them
    doc.reload()
    rebuild_brand_summary(doc)
    recalc_doc_totals(doc)

    # Persist parent totals (bypasses submit-validation for fields
    # without allow_on_submit=1).
    parent_updates = {
        "custom_total_shipping_new":       flt(doc.get("custom_total_shipping_new") or 0, 4),
        "custom_total_finance_new":        flt(doc.get("custom_total_finance_new") or 0, 4),
        "custom_total_transport_new":      flt(doc.get("custom_total_transport_new") or 0, 4),
        "custom_total_reward_new":         flt(doc.get("custom_total_reward_new") or 0, 4),
        "custom_total_incentive_new":      flt(doc.get("custom_total_incentive_new") or 0, 4),
        "custom_total_customs_new":        flt(doc.get("custom_total_customs_new") or 0, 4),
        "custom_total_margin_new":         flt(doc.get("custom_total_margin_new") or 0, 4),
        "custom_total_margin_percent_new": flt(doc.get("custom_total_margin_percent_new") or 0, 4),
        "custom_total_cost_new":           flt(doc.get("custom_total_cost_new") or 0, 4),
        "custom_total_selling_new":        flt(doc.get("custom_total_selling_new") or 0, 4),
        "custom_total_buying_price":       flt(doc.get("custom_total_buying_price") or 0, 4),
    }

    # Keep the parent Incentive fields in step with what the rows now carry.
    #
    # The loop above re-derives every row's incentive from its own percentage
    # against the NEW special price, so custom_total_incentive_new moves — but
    # custom_incentive_amount / custom_incentive_ were left holding the figures
    # that belonged to the OLD prices. Parent and rows then disagreed for good,
    # which is the same drift the draft pipeline had before _sync_incentive_
    # fields() was wired into it. The sibling "Update Items" flow avoids this by
    # going through _finalize_submitted_quotation_save(); this older
    # "Update Special Price" flow writes rows straight to the DB and never did.
    #
    # Rows are treated as the source of truth here rather than redistributing to
    # hold custom_incentive_amount fixed: redistribution would move each row's
    # COGS, and this function's contract is that Selling Price / Rate / Amount —
    # and therefore every customer-facing figure — stay exactly as they were.
    total_sp_now = sum(
        flt(_to_flt(r.custom_special_price) * max(cint(r.qty), 1)) for r in doc.items
    )
    synced_incentive = flt(doc.get("custom_total_incentive_new") or 0, 4)
    incentive_pct = _safe_pct(synced_incentive, total_sp_now)
    parent_updates["custom_incentive_amount"] = synced_incentive
    parent_updates["custom_incentive_"] = incentive_pct
    # Same number, same base as recalc_doc_totals' custom_total_incentive_
    # percent_new — total_sp_now is that function's totals["buying_price"],
    # computed identically. This flow writes rows straight to the DB and never
    # runs recalc_doc_totals, so the derived total has to be restated here or
    # it keeps the figure that belonged to the OLD special prices.
    parent_updates["custom_total_incentive_percent_new"] = incentive_pct

    frappe.db.set_value("Quotation", quotation_name, parent_updates, update_modified=True)

    # Rebuild the Brand Summary child rows in DB: rebuild_brand_summary
    # populated doc.custom_quotation_brand_summary in memory; persist
    # them via delete + insert. Submitted-doc save would require every
    # field to be allow_on_submit, so we go around it with raw rows.
    BS_DT = "Quotation Brand Summary"
    BS_FIELDS = (
        "brand", "buying_price",
        "shipping", "shipping_percent",
        "finance", "finance_percent",
        "processing", "processing_percent",
        "reward", "reward_percent",
        "incentive", "incentive_percent",
        "customs", "customs_",
        "total_cost", "total_selling",
        "margin", "margin_percent", "std_margin_percent",
        "approval_status",
    )
    frappe.db.delete(BS_DT, {"parent": quotation_name, "parenttype": "Quotation"})
    for idx, bs in enumerate(doc.get("custom_quotation_brand_summary") or [], start=1):
        bs_doc = frappe.new_doc(BS_DT)
        bs_doc.parent = quotation_name
        bs_doc.parenttype = "Quotation"
        bs_doc.parentfield = "custom_quotation_brand_summary"
        bs_doc.idx = idx
        for fn in BS_FIELDS:
            val = bs.get(fn)
            if val is not None:
                bs_doc.set(fn, val)
        bs_doc.db_insert()

    frappe.db.set_value("Quotation", quotation_name, "modified", frappe.utils.now())
    frappe.db.commit()

    return {"message": "Special Price updated successfully"}


@frappe.whitelist()
def update_items_selling_price(quotation_name, items):
    """Update Qty / Special Price / Selling Price (incl. adding new
    rows) on a submitted Quotation from the "Update Items" flow (only
    reachable while workflow_state is "Approved for Update" — see
    quotation.js _strip_update_items).

    Sridhar 2026-07-24 (meeting decision 2026-07-22): ERPNext's native
    Update Items dialog (erpnext.utils.update_child_items) edits the
    core `rate` field directly. But `rate` is a MIRROR field here —
    calc_item_totals always overwrites it from custom_special_price +
    custom_markup_. This dialog instead edits Special Price / Selling
    Price directly and back-solves markup% (_apply_manual_selling_rate,
    same formula a manual rate edit gets on a Draft quote) so the
    entered price is what actually persists.

    Sridhar 2026-07-24 (same-day rewrite #2 — Sales feedback: "how does
    Tax work here, make this behave like default ERPNext"): the first
    cut of this function persisted via raw frappe.db.set_value,
    bypassing doc.save() entirely — which also skipped Sales Taxes and
    Charges recalculation. Root cause of the original "bypass" design:
    submitted-doc fields here aren't allow_on_submit, so a plain
    doc.save() throws "Not allowed to change after submission".

    ERPNext's own update_child_qty_rate (erpnext/controllers/
    accounts_controller.py) solves the same problem the same way: it
    sets `doc.flags.ignore_validate_update_after_submit = True`, which
    Frappe's Document.validate_update_after_submit() checks first and
    short-circuits on (frappe/model/document.py:932-943), then calls
    `parent.calculate_taxes_and_totals()` and `parent.save()`. Adopted
    below.

    Correction (same day, caught while answering a follow-up question):
    an earlier version of this docstring claimed the switch to
    doc.save() ALSO restores validate-time hooks like
    validate_item_tax_template (GST/tax-template auto-fill). That's
    wrong — verified against Frappe's actual source. This save is
    docstatus 1 -> 1, which Frappe tags `_action = "update_after_submit"`
    (Document.check_docstatus_transition). In that branch,
    run_before_save_methods() calls ONLY before_update_after_submit —
    it skips the entire "validate" and "before_save" hook lists
    (document.py:1142-1151), unconditionally, regardless of doc.save()
    vs raw SQL. So run_calculation_pipeline, validate_item_tax_template,
    validate_margin_approval_required, validate_total_discount, etc.
    NEVER fire here — not because their own guards happen to allow it,
    but because Frappe doesn't call them at all for this action. Only
    `on_update_after_submit` hooks fire (post-save) — checked those are
    safe: quotation_high_probability's hook explicitly allows
    workflow_state "Approved for Update", validate_probability_change_
    approval / notify_probability_100 no-op since probability is
    untouched, sync_workflow_status is idempotent.

    Net effect: anything from the normal validate/before_save chain
    that still matters here must be called explicitly — see
    _finalize_submitted_quotation_save() below, shared with
    apply_discount_on_submitted() / apply_incentive_on_submitted().

    Sridhar 2026-07-24 (same day, 4th pass — remove-row support +
    Discount/Incentive rebasing): row removal is a set-diff against
    what the dialog sent (see below); an existing parent-level Discount
    or Incentive (percentage-driven) is automatically rebased against
    the changed item total via _finalize_submitted_quotation_save(),
    with a msgprint telling the user it happened — items were bought at
    a % off/incentive, adding or removing rows shouldn't silently leave
    that stale against the old total.
    """
    items = frappe.parse_json(items)
    doc = frappe.get_doc("Quotation", quotation_name)
    _guard_quotation_editable_for_update(doc)

    existing_by_name = {r.name: r for r in doc.items}
    touched_any = False

    for item_update in items:
        row_name = item_update.get("name")
        item_code = item_update.get("item_code")
        new_qty = flt(item_update.get("qty"))
        new_rate = flt(item_update.get("custom_special_rate"))
        sp_override = item_update.get("custom_special_price")
        if new_qty <= 0 or new_rate <= 0:
            continue

        row = existing_by_name.get(row_name) if row_name else None

        if row:
            # ── Existing row: Qty / Special Price / Selling Price edit ──
            row.qty = new_qty
            if sp_override not in (None, ""):
                row.custom_special_price = flt(sp_override)
            # Qty-scaled cost components (shipping/finance/transport/
            # reward/incentive/customs) + a formula rate we override next.
            calc_item_totals(row)
            # Back-solve custom_markup_ so the entered per-unit price is
            # what persists — same formula a manual rate edit on a Draft
            # quote uses.
            _apply_manual_selling_rate(row, new_rate)
            touched_any = True

        else:
            # ── New row: item added via "Add Row" while Approved for
            # Update. item_code is mandatory — the client already blocks
            # submitting without one, this is the server-side backstop.
            if not item_code:
                continue

            item_master = frappe.db.get_value(
                "Item", item_code,
                ["item_name", "description", "stock_uom", "disabled"],
                as_dict=True,
            )
            if not item_master:
                frappe.throw(_("Item {0} not found.").format(item_code))
            if item_master.disabled:
                frappe.throw(_("Item {0} is disabled.").format(item_code))

            defaults = get_item_defaults(
                item_code, doc.selling_price_list, doc.currency,
                doc.price_list_currency, doc.plc_conversion_rate, doc.company,
            )
            if defaults.get("no_price_for_company"):
                frappe.throw(_(
                    "No Item Price found for {0} in company {1}. Please set "
                    "up an Item Price before adding it here."
                ).format(item_code, doc.company))

            std_price = flt(defaults.get("custom_standard_price_"))
            new_special_price = flt(sp_override) if sp_override not in (None, "") else flt(defaults.get("custom_special_price"))
            if not std_price and not new_special_price:
                frappe.throw(_(
                    "No Item Price found for {0}. Set one up, or provide a "
                    "Special Price manually, before adding it here."
                ).format(item_code))

            new_row = doc.append("items", {})
            new_row.item_code = item_code
            new_row.item_name = item_master.item_name or item_code
            new_row.description = item_master.description or item_master.item_name
            new_row.uom = item_master.stock_uom
            new_row.stock_uom = item_master.stock_uom
            new_row.conversion_factor = 1
            new_row.qty = new_qty

            new_row.custom_standard_price_ = std_price
            new_row.custom_special_price = new_special_price
            # This dialog's item payload has no per-row Shipping Mode column
            # (see show_update_items_selling_price_dialog) — a newly added
            # row inherits the quotation's own mode, same effective-mode
            # fallback the Draft-time JS/server logic uses elsewhere.
            new_row.custom_shipping_mode = doc.custom_shipping_mode
            new_row.shipping_per = _default_shipping_per_for_mode(doc.custom_shipping_mode, defaults)
            new_row.custom_transport_ = flt(defaults.get("custom_transport_"))
            new_row.custom_finance_ = flt(defaults.get("custom_finance_"))
            new_row.std_margin_per = flt(defaults.get("std_margin_per"))
            new_row.custom_customs_ = flt(defaults.get("custom_customs_"))
            new_row.custom_markup_ = flt(defaults.get("custom_markup_"))

            calc_item_totals(new_row)
            _apply_manual_selling_rate(new_row, new_rate)
            touched_any = True

    # ── Row removal ── the dialog always sends the FULL current item
    # list (it's a whole-table editor, not a delta view — every existing
    # row starts pre-populated), so any existing row whose name is
    # missing from the payload was deliberately removed by the user via
    # the grid's delete checkbox. Diffing against what was sent is a
    # reliable "delete" signal here for exactly that reason; it would
    # NOT be safe for a partial-update API.
    sent_names = {u.get("name") for u in items if u.get("name")}
    removed_names = set(existing_by_name.keys()) - sent_names
    if removed_names:
        doc.set("items", [r for r in doc.items if r.name not in removed_names])
        touched_any = True

    if not touched_any:
        frappe.throw(_("No valid item changes to apply."))
    if not doc.items:
        frappe.throw(_("A Quotation must have at least one item — cannot remove all items."))

    # Correction (Sridhar 2026-07-24, same day): this save is docstatus
    # 1 -> 1, which Frappe tags _action = "update_after_submit"
    # (frappe/model/document.py check_docstatus_transition). In THAT
    # branch, run_before_save_methods() calls ONLY
    # before_update_after_submit — it skips the "validate" and
    # "before_save" hook lists entirely (document.py:1142-1151). So NONE
    # of Quotation's validate/before_save hooks fire here regardless of
    # doc.save() vs raw SQL. _finalize_submitted_quotation_save() below
    # is what replaces them: GST/tax-template validation, Discount/
    # Incentive redistribution (rebased against the now-changed item
    # set — the mixed-GST / add-remove-row concern this function exists
    # for), Brand Summary + custom total fields, and ERPNext's own Sales
    # Taxes and Charges / payment schedule recalculation, all in the
    # order that keeps them mutually consistent (see that function's
    # docstring for exactly why the order matters).
    _finalize_submitted_quotation_save(doc, notify_discount_incentive_reapply=True)

    return {"message": "Items updated successfully"}


@frappe.whitelist()
def apply_discount_on_submitted(quotation_name, discount_type, discount_percentage=0, discount_amount=0):
    """Apply Discount (custom_discount_type / custom_discount_ /
    custom_discount_amount_value) on a submitted Quotation, while
    workflow_state is "Approved for Update". Sridhar 2026-07-24: the
    Discount and Incentive section's Apply buttons only ever computed a
    client-side preview and relied on a later full frm.save() to
    persist — which hard-fails on a submitted doc (these fields aren't
    allow_on_submit). This is the bypass-save persistence layer for
    that button when frm.doc.docstatus === 1, mirroring
    update_items_selling_price's pattern exactly.
    """
    doc = frappe.get_doc("Quotation", quotation_name)
    _guard_quotation_editable_for_update(doc)

    doc.custom_discount_type = discount_type or "Amount"
    doc.custom_discount_ = flt(discount_percentage)
    doc.custom_discount_amount_value = flt(discount_amount)
    if not doc.custom_discount_ and not doc.custom_discount_amount_value:
        frappe.throw(_("Enter a discount percentage or amount."))

    _finalize_submitted_quotation_save(doc)

    return {"message": "Discount applied successfully"}


@frappe.whitelist()
def apply_incentive_on_submitted(quotation_name, incentive_type, incentive_percentage=0, incentive_amount=0):
    """Apply Incentive (custom_incentive_type / custom_incentive_ /
    custom_incentive_amount) on a submitted Quotation — sibling to
    apply_discount_on_submitted() above, same rationale."""
    doc = frappe.get_doc("Quotation", quotation_name)
    _guard_quotation_editable_for_update(doc)

    doc.custom_incentive_type = incentive_type or "Percentage"
    doc.custom_incentive_ = flt(incentive_percentage)
    doc.custom_incentive_amount = flt(incentive_amount)
    if not doc.custom_incentive_ and not doc.custom_incentive_amount:
        frappe.throw(_("Enter an incentive percentage or amount."))

    _finalize_submitted_quotation_save(doc)

    return {"message": "Incentive applied successfully"}


@frappe.whitelist()
def apply_shipping_on_submitted(quotation_name, shipping_mode):
    """Apply a new doc-level Shipping Mode on a submitted Quotation, while
    workflow_state is "Approved for Update" — sibling to
    apply_discount_on_submitted() / apply_incentive_on_submitted() above.

    Unlike Discount/Incentive (a post-hoc adjustment layered ON TOP of an
    already-computed selling price via distribute_discount_server /
    distribute_incentive_server), Shipping % is itself one of
    calc_item_totals' Layer-1 cost inputs — changing it changes COGS,
    which cascades through markup and selling price. So this can't just
    redistribute a fixed amount across rows the way Discount/Incentive
    do; every item has to be re-run through calc_item_totals from its own
    new shipping_per (mirroring what changing the doc-level Shipping Mode
    does on a Draft, per update_items_shipping_percent in quotation.js).
    Any existing Discount/Incentive is then re-applied against those
    recomputed prices by _finalize_submitted_quotation_save, exactly like
    it already does for update_items_selling_price's add/remove/reprice
    flow (notify_discount_incentive_reapply)."""
    doc = frappe.get_doc("Quotation", quotation_name)
    _guard_quotation_editable_for_update(doc)

    doc.custom_shipping_mode = shipping_mode

    # Cascade to every row's own custom_shipping_mode too, not just
    # shipping_per — mirrors the Draft-time fix in update_items_shipping_
    # percent() (quotation.js): a doc-level change is a full reset of
    # every line's mode, matching what the Items grid column then shows.
    # A user can still override any individual row afterward (the normal
    # per-row edit path, untouched by this).
    for it in doc.items:
        if not it.item_code:
            continue
        it.custom_shipping_mode = shipping_mode
        if shipping_mode in ("EXW", "DDP"):
            it.shipping_per = 0
        else:
            defaults = get_item_defaults(
                it.item_code,
                doc.selling_price_list,
                doc.currency,
                doc.price_list_currency,
                doc.plc_conversion_rate,
                doc.company,
            )
            if not defaults.get("no_price_for_company"):
                it.shipping_per = _default_shipping_per_for_mode(shipping_mode, defaults)
        calc_item_totals(it)

    _finalize_submitted_quotation_save(doc, notify_discount_incentive_reapply=True)

    return {"message": "Shipping mode applied successfully"}


# Venkatesh/Rahul 2026-06-11 ERP-TKT-31: Quote print should be gated
# on Approval — users keep generating PDFs of draft/pending quotes and
# share them with customers, then the price changes on L2 approval and
# the customer was already quoted the wrong number. Block server-side
# so PDF API + email-with-print can't sneak past the JS button hide.
_PRINT_ALLOWED_STATES = frozenset({
    "Approved",         # V3 terminal-approved
    "Submitted",        # legacy
    "Order Placed",     # post-conversion to SO
    "Quotation Closed", # post-conversion / explicit close
    # Note: Cancellation Requested / Cancelled / Rejected are NOT here
    # — once Rejected/Cancelled the print is also blocked (those quotes
    # shouldn't go out as PDFs either).
})


def block_print_unless_approved(doc, method=None, *args, **kwargs):
    """`before_print` hook on Quotation. Sales/Accounts/CS staff stay
    blocked; System Manager / Administrator can always print (audit /
    historical record).

    Hooked via doc_events["Quotation"]["before_print"] in hooks.py.

    Signature note: Frappe's `run_method("before_print", print_settings)`
    routes through Document.hook's composer at `model/document.py:1374`
    which calls `composed(self, method, *args, **kwargs)`. The third
    positional arg (`print_settings`) blew up the 2-arg signature on
    prod after the 2026-06-11 Bench Update (TypeError: takes from 1 to
    2 positional arguments but 3 were given — Quotation print
    completely broken). `*args, **kwargs` here absorbs `print_settings`
    + any future positional args Frappe adds. We don't USE
    print_settings; the gate only cares about workflow_state + roles.
    """
    ws = (getattr(doc, "workflow_state", None) or "").strip()
    if ws in _PRINT_ALLOWED_STATES:
        return

    user = frappe.session.user
    if user == "Administrator":
        return
    roles = set(frappe.get_roles(user))
    if "System Manager" in roles:
        return

    frappe.throw(
        _(
            "This Quotation is in <b>{0}</b> state. Printing is only "
            "permitted once the Quotation reaches <b>Approved</b>. "
            "Please complete the approval workflow first."
        ).format(ws or "Draft"),
        title=_("Print Not Allowed"),
    )
