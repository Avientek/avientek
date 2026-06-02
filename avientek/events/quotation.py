import frappe
from frappe import _
from frappe.utils import flt, cint
from frappe.model.workflow import apply_workflow
import json
from decimal import Decimal, ROUND_HALF_UP


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
        if new_selling < 0:
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
            if selling_rate else Decimal("0.0")
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
        if total_selling else 0.0
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
        "stock": get_company_stock(item_code),
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
        AND so.name NOT IN (
            SELECT DISTINCT sii.sales_order
            FROM `tabSales Invoice Item` sii
            WHERE sii.sales_order IS NOT NULL
        )
        ORDER BY so.transaction_date DESC
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
          AND q.name NOT IN (
              SELECT DISTINCT soi.prevdoc_docname
              FROM `tabSales Order Item` soi
              WHERE soi.prevdoc_docname IS NOT NULL
          )
        ORDER BY q.transaction_date DESC
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
def get_company_stock(item_code):
    stock = []

    companies = frappe.get_all("Company", pluck="name")

    for company in companies:
        warehouses = frappe.get_all(
            "Warehouse",
            filters={
                "company": company,
                "is_group": 0
            },
            pluck="name"
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
            "company": company,
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


# ──────────────────────────────────────────────────────────────
# 1)  PER-ITEM CALCULATION  (server-side — single source of truth)
#     Verified formula from client spreadsheet (ERP_Next.ods)
# ──────────────────────────────────────────────────────────────
def calc_item_totals(it):
    qty = max(cint(it.qty), 1)

    std_price = _to_flt(it.custom_standard_price_)
    sp        = _to_flt(it.custom_special_price)

    # Skip calculation if no custom pricing is configured (no Item Price setup).
    # Preserve manually entered rate/amount so they don't get zeroed out on save.
    if not std_price and not sp:
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

    # Final values
    selling = flt(cogs + markup, 4)                    # selling = cogs + markup

    # Margin: selling - cogs = markup (margin is the profit from markup)
    margin_val = flt(selling - cogs, 4)
    margin_pct = flt(margin_val / selling * 100, 4) if selling else 0.0

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
        b = it.brand or "Unbranded"
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

        effective_ts = flt(ts - brand_addl, 4)
        brand_margin_pct = flt((effective_ts - tc) / effective_ts * 100, 4) if effective_ts else 0

        # Weighted average std margin for the brand
        std_margin_percent = (
            d["std_margin_weighted_sum"] / d["selling_weight_sum"]
            if d["selling_weight_sum"] > 0 else 0
        )

        doc.append("custom_quotation_brand_summary", {
            "brand":              brand,
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
            "incentive_percent":  flt(d["incentive_percent"] / n, 4),
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
        if ts:
            doc.additional_discount_percentage = flt(addl_discount / ts * 100, 4)

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
            effective_item_selling = flt(item_selling - item_addl, 4)
            item_cost = _to_flt(it.custom_cogs)
            it.custom_margin_value = flt(effective_item_selling - item_cost, 4)
            it.custom_margin_ = flt(
                (it.custom_margin_value / effective_item_selling * 100) if effective_item_selling else 0, 4
            )
        else:
            it.custom_addl_discount_amount = 0

    effective_selling = flt(ts - addl_discount, 4)

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
    margin_pct = flt(margin / effective_selling * 100, 4) if effective_selling else 0

    doc.custom_total_shipping_new       = flt(totals["shipping"], 4)
    doc.custom_total_finance_new        = flt(totals["finance"], 4)
    doc.custom_total_transport_new      = flt(totals["transport"], 4)
    doc.custom_total_reward_new         = flt(totals["reward"], 4)
    doc.custom_total_incentive_new      = flt(totals["incentive"], 4)
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

    doc.total_qty      = flt(total_qty, 4)
    doc.total          = flt(item_amount_sum, 4)
    doc.net_total      = flt(item_amount_sum, 4)
    doc.base_total     = flt(item_amount_sum * conversion_rate, 4)
    doc.base_net_total = flt(item_amount_sum * conversion_rate, 4)

    # ── Recalculate taxes from the Taxes table ──
    # ERPNext's calculate_taxes_and_totals ran during validate with stale
    # item amounts.  Recompute each tax row based on our updated net_total.
    net_after_discount = flt(item_amount_sum - addl_discount, 4)
    total_taxes = 0
    for tax_row in (doc.get("taxes") or []):
        if tax_row.charge_type == "On Net Total":
            tax_row.tax_amount = flt(flt(tax_row.rate) * net_after_discount / 100, 4)
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

    # Sum of all item (sp * qty) for proportional distribution
    total_sp = sum(flt(_to_flt(it.custom_special_price) * max(cint(it.qty), 1)) for it in items)
    if not total_sp:
        return

    for it in items:
        qty = max(cint(it.qty), 1)
        sp = _to_flt(it.custom_special_price)
        cogs = _to_flt(it.custom_cogs)
        markup = _to_flt(it.custom_markup_value)
        old_incentive = _to_flt(it.custom_incentive_value)  # incentive already in cogs

        # Distribute incentive
        if mode == "Distributed Equally":
            row_incentive = flt(total_incentive / len(items), 4)
        else:  # "Amount" — proportional to sp * qty
            row_incentive = flt((sp * qty / total_sp) * total_incentive, 4)

        # Remove old incentive from cogs, then add new distributed incentive
        cogs_without_incentive = flt(cogs - old_incentive, 4)
        adjusted_cost = flt(cogs_without_incentive + row_incentive, 4)

        # Selling = adjusted cost + markup (markup stays the same)
        selling = flt(adjusted_cost + markup, 4)
        per_unit_selling = flt(selling / qty, 4)

        # Margin
        margin_val = flt(selling - adjusted_cost, 4)
        margin_pct = flt(margin_val / selling * 100, 4) if selling else 0

        it.update({
            "custom_incentive_value": row_incentive,
            "custom_incentive_":     flt(row_incentive / (sp * qty) * 100, 4) if sp else 0,
            "custom_cogs":           adjusted_cost,
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
        new_selling = flt(selling - item_discount, 4)
        if new_selling < 0:
            new_selling = 0

        new_rate = flt(new_selling / qty, 4) if qty else 0

        # Margin recalculation (after discount)
        margin_val = flt(new_selling - cogs, 4)
        if margin_val < 0:
            margin_val = 0
        margin_pct = flt(margin_val / new_selling * 100, 4) if new_selling else 0

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
    markup_pct = flt(markup_val / cogs * 100, 4)
    margin_val = flt(user_selling - cogs, 4)
    margin_pct = flt(margin_val / user_selling * 100, 4) if user_selling else 0.0

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


def run_calculation_pipeline(doc, method=None):
    """Authoritative server-side calculation — runs on every save.
    Skip on submit/cancel/amend to preserve the previewed values."""
    if doc.docstatus != 0:
        return

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

    # Distribute parent-level incentive only when parent has a positive amount.
    # calc_item_totals already computes item-level incentive from each item's
    # custom_incentive_ percentage; the distributor overrides that with the
    # parent-controlled amount.
    incentive_amount = _to_flt(doc.custom_incentive_amount)
    if incentive_amount > 0:
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
    percentage = (doc.discount_amount / base_amount) * 100

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


def copy_first_item_part_number(doc, method=None):
    """Sridhar/Rahul 2026-05-29 (updated 2026-06-01): surface the item rows'
    part_number onto the Quotation parent so Report View can use clean
    parent-level columns instead of hitting the (Quotation, Quotation Item)
    child-table collision between `items` and `custom_service_items`.

    Sridhar 2026-06-01: split into TWO parent fields so the report can
    show item part numbers and optional-item part numbers separately:

      - `first_item_part_number` (label 'Item Part Number') ←  items[]
      - `optional_item_part_numbers` (label 'Optional Item Part Number') ←
        custom_service_items[]

    Each value is the comma-joined, order-preserving, dedup'd list of
    non-empty part_number values from its source child table. Fieldname
    `first_item_part_number` stays unchanged for historical compatibility
    with the API-created Custom Field.
    """
    def _join(rows):
        seen = set()
        parts = []
        for row in rows or []:
            pn = (row.get("part_number") or "").strip()
            if not pn or pn in seen:
                continue
            seen.add(pn)
            parts.append(pn)
        return ", ".join(parts)

    new_items = _join(doc.get("items"))
    if (doc.get("first_item_part_number") or "") != new_items:
        doc.first_item_part_number = new_items

    new_optional = _join(doc.get("custom_service_items"))
    if (doc.get("optional_item_part_numbers") or "") != new_optional:
        doc.optional_item_part_numbers = new_optional


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

    Explicit sync on every validate keeps both fields aligned. Cheap
    Python assignment, no DB roundtrip — fires regardless of how the
    save was triggered (workflow action, direct save, API, etc.).
    """
    current_state = doc.get("workflow_state") or ""
    current_status = doc.get("workflow_status") or ""
    if current_state != current_status:
        doc.workflow_status = current_state


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
        margin = ((flt(r.rate) - cogs_per_unit) / flt(r.rate)) * 100
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
        margin_pct = flt(margin_val / selling * 100, 4) if selling else 0.0

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
