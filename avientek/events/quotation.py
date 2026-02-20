import frappe
from frappe.utils import flt
from frappe.utils import flt, cint
from frappe.model.workflow import apply_workflow
import json
from decimal import Decimal, ROUND_HALF_UP


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

    filters = {
        "item_code": item_code,
        "price_list": price_list
    }
    if company:
        filters["custom_company"] = company

    data = frappe.db.get_value(
        "Item Price",
        filters,
        [
            "custom_shipping__air_",
            "custom_shipping__sea_",
            "custom_min_margin_",
            "custom_markup_",
        ],
        as_dict=True
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


# ──────────────────────────────────────────────────────────────
# 1)  PER-ITEM CALCULATION  (server-side — single source of truth)
#     Verified formula from client spreadsheet (ERP_Next.ods)
# ──────────────────────────────────────────────────────────────
def calc_item_totals(it):
    qty = max(cint(it.qty), 1)

    std_price = _to_flt(it.custom_standard_price_)
    sp        = _to_flt(it.custom_special_price)

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
        bk["cnt"]                += 1

    doc.set("custom_quotation_brand_summary", [])
    for brand, d in buckets.items():
        n = d.pop("cnt") or 1
        ts = d["total_selling"]
        tc = d["total_cost"]
        brand_margin_pct = flt((ts - tc) / ts * 100, 4) if ts else 0

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
            "total_selling":      flt(ts, 4),
            "margin":             flt(ts - tc, 4),
            "margin_percent":     brand_margin_pct,
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
    margin = flt(ts - tc, 4)
    margin_pct = flt(margin / ts * 100, 4) if ts else 0

    doc.custom_total_shipping_new       = flt(totals["shipping"], 4)
    doc.custom_total_finance_new        = flt(totals["finance"], 4)
    doc.custom_total_transport_new      = flt(totals["transport"], 4)
    doc.custom_total_reward_new         = flt(totals["reward"], 4)
    doc.custom_total_incentive_new      = flt(totals["incentive"], 4)
    doc.custom_total_customs_new        = flt(totals["customs"], 4)
    doc.custom_total_margin_new         = margin
    doc.custom_total_margin_percent_new = margin_pct
    doc.custom_total_cost_new           = flt(tc, 4)
    doc.custom_total_selling_new        = flt(ts, 4)
    doc.custom_total_buying_price       = flt(totals["buying_price"], 4)


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


# ──────────────────────────────────────────────────────────────
# 5)  MASTER PIPELINE  (called from before_save hook)
# ──────────────────────────────────────────────────────────────
def run_calculation_pipeline(doc, method=None):
    """Authoritative server-side calculation — runs on every save."""
    for it in doc.items:
        calc_item_totals(it)

    # Distribute parent-level incentive only when parent has a positive amount.
    # calc_item_totals already computes item-level incentive from each item's
    # custom_incentive_ percentage; the distributor overrides that with the
    # parent-controlled amount.
    incentive_amount = _to_flt(doc.custom_incentive_amount)
    if incentive_amount > 0:
        distribute_incentive_server(doc)

    # Distribute parent-level discount only when parent has a positive amount.
    # calc_item_totals resets item discount fields to 0, so stale values
    # from a previous "Apply Discount" no longer trigger redistribution.
    discount_amount = _to_flt(doc.custom_discount_amount_value)
    if discount_amount > 0:
        distribute_discount_server(doc)

    rebuild_brand_summary(doc)
    recalc_doc_totals(doc)


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
    ip_filters = {"item_code": item_code, "price_list": price_list}
    if company:
        ip_filters["custom_company"] = company

    ip = frappe.db.get_value(
        "Item Price",
        ip_filters,
        [
            "price_list_rate",
            "custom_shipping__air_",
            "custom_shipping__sea_",
            "custom_processing_",
            "custom_min_finance_charge_",
            "custom_min_margin_",
            "custom_customs_",
            "custom_markup_",
        ],
        as_dict=True,
    )

    if not ip and company:
        # No Item Price for this company — signal to client
        result["no_price_for_company"] = True
        result["item_code"] = item_code
        result["company"] = company
        result["price_list"] = price_list
        return result

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


def get_overall_margin(salesperson, brand):
    if not (salesperson and brand):
        return 0

    date_cut = frappe.db.get_single_value(
        "Selling Settings", "custom_applicable_date"
    )

    cond = """
        q.docstatus = 1
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
    doc.custom_auto_approve_ok = 1
    doc.custom_level_1_approve_ok = 0

    salesperson = doc.sales_person

    level_1_required = False
    level_2_required = False

    for row in doc.items:
        std = flt(row.std_margin_per)
        new = flt(row.custom_margin_)
        brand = row.brand

        # 1️⃣ Auto approval (no warning)
        if new >= std or new >= (0.80 * std):
            continue

        # 2️⃣ Auto approval with warning
        if new >= (0.60 * std):
            overall = get_overall_margin(salesperson, brand)
            if overall >= (0.80 * std):
                frappe.msgprint(
                    f"""
                    Brand <b>{brand}</b><br>
                    Current Margin : <b>{round(new, 2)}%</b><br>
                    Standard Margin : <b>{round(std, 2)}%</b><br>
                    Short by : <b>{round(std - new, 2)}%</b><br>
                    """,
                    title="Margin Warning",
                    indicator="orange"
                )

                # frappe.msgprint(
                #     "Current margin below standard, but historical overall margin is healthy."
                # )
                continue

            level_1_required = True
            continue

        # 3️⃣ Level 2 approval
        level_2_required = True
    # 🔻 Final decision (AFTER checking all items)

    if level_2_required:
        doc.custom_auto_approve_ok = 0
        doc.custom_level_1_approve_ok = 0

    elif level_1_required:
        doc.custom_auto_approve_ok = 0
        doc.custom_level_1_approve_ok = 1
