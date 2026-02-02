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
    if discount <= 0:
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
        frappe.errprint(f"Item {name}: Original Selling: {selling}, Discount: {item_discount}, New Selling: {new_selling}")
        if new_selling < 0:
            new_selling = Decimal("0.0")

        new_rate = new_selling / qty if qty else Decimal("0.0")
        frappe.errprint(f"Item {name}: New Rate: {new_rate}")
        # Margin recalculation
        cost_rate = Decimal(str((i.get("custom_cogs") or 0)))
        frappe.errprint(f"Item {name}: Cost Rate: {cost_rate}")
        selling_rate = new_selling

        new_margin_val = (selling_rate - cost_rate)
        frappe.errprint(f"Item {name}: New Margin Value: {new_margin_val}")
        if new_margin_val < 0:
            new_margin_val = Decimal("0.0")

        new_margin_pct = (
            ((selling_rate - cost_rate) / selling_rate) * 100
            if selling_rate else Decimal("0.0")
        )
        frappe.errprint(f"Item {name}: New Margin Percent: {new_margin_pct}")

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
def get_item_all_details(item_code, customer,price_list):
    return {
        "history": get_last_5_transactions(item_code, customer),
        "stock": get_company_stock(item_code),
        "shipment_margin": get_shipment_and_margin(item_code, price_list)
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
def get_shipment_and_margin(item_code, price_list):
    if not item_code or not price_list:
        return {}

    data = frappe.db.get_value(
        "Item Price",
        {
            "item_code": item_code,
            "price_list": price_list
        },
        [
            "custom_shipping__air_",
            "custom_shipping__sea_",
            "custom_min_margin_"
        ],
        as_dict=True
    )

    if not data:
        return {}

    return {
        "ship_air": data.custom_shipping__air_ or 0,
        "ship_sea": data.custom_shipping__sea_ or 0,
        "std_margin": data.custom_min_margin_ or 0
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
# 1)  PER-ITEM CALCULATION  (server-side replacement of JS
#     calculate_all  +  calculate_custom_rate)
# ──────────────────────────────────────────────────────────────
def calc_item_totals(it):
    qty = max(cint(it.qty), 1)

    std_price = _to_flt(it.custom_standard_price_)
    sp        = _to_flt(it.custom_special_price)

    shipping   = _to_flt(it.shipping_per)      * std_price / 100 * qty
    finance    = _to_flt(it.custom_finance_)   * sp        / 100 * qty
    transport  = _to_flt(it.custom_transport_) * std_price / 100 * qty
    reward     = _to_flt(it.reward_per)        * sp        / 100 * qty

    base_amt   = sp * qty + shipping + finance + transport + reward
    incentive  = _to_flt(it.custom_incentive_) * base_amt / 100
    cogs       = base_amt + incentive
    markup     = _to_flt(it.custom_markup_)    * cogs     / 100
    total      = cogs + markup

    customs    = _to_flt(it.custom_customs_)   * total    / 100
    selling    = total + customs

    margin_pct = (markup / total * 100) if total else 0
    margin_val = margin_pct / 100 * total

    # write back on the child doc
    it.update({
        "shipping"                 : shipping,
        "custom_finance_value"     : finance,
        "custom_transport_value"   : transport,
        "reward"                   : reward,
        "custom_incentive_value"   : incentive,
        "custom_markup_value"      : markup,
        "custom_cogs"              : cogs,
        "custom_total_"            : total,
        "custom_margin_"           : margin_pct,
        "custom_margin_value"      : margin_val,
        "custom_customs_value"     : customs,
        "custom_selling_price"     : selling,
        "custom_special_rate"      : selling / qty,
        "rate"                     : selling / qty,
    })


# ──────────────────────────────────────────────────────────────
# 2)  BRAND SUMMARY  (server-side replacement of JS
#     calculate_brand_summary)
# ──────────────────────────────────────────────────────────────
# def rebuild_brand_summary(doc):
#     buckets = {}

#     for it in doc.items:
#         b = it.brand or "?"
#         if b not in buckets:
#             buckets[b] = {
#                 "shipping":0,"shipping_percent":0,
#                 "finance":0,"finance_percent":0,
#                 "transport":0,"transport_percent":0,
#                 "reward":0,"reward_percent":0,
#                 "incentive":0,"incentive_percent":0,
#                 "customs":0,"customs_percent":0,
#                 "total_cost":0,"total_selling":0,
#                 "margin":0,"margin_percent":0,
#                 "cnt":0,
#             }

#         bk = buckets[b]
#         bk["shipping"]          += it.shipping
#         bk["shipping_percent"]  += _to_flt(it.shipping_per)
#         bk["finance"]           += it.custom_finance_value
#         bk["finance_percent"]   += _to_flt(it.custom_finance_)
#         bk["transport"]         += it.custom_transport_value
#         bk["transport_percent"] += _to_flt(it.custom_transport_)
#         bk["reward"]            += it.reward
#         bk["reward_percent"]    += _to_flt(it.reward_per)
#         bk["incentive"]         += it.custom_incentive_value
#         bk["incentive_percent"] += _to_flt(it.custom_incentive_)
#         bk["customs"]           += it.custom_customs_value
#         bk["customs_percent"]   += _to_flt(it.custom_customs_)
#         bk["total_cost"]        += it.custom_cogs
#         bk["total_selling"]     += it.custom_selling_price
#         bk["margin"]            += it.custom_markup_value
#         bk["margin_percent"]    += it.custom_margin_
#         bk["cnt"]               += 1

#     doc.set("custom_brand_summary", [])
#     for brand, d in buckets.items():
#         n = d.pop("cnt") or 1
#         doc.append("custom_brand_summary", {
#             "brand": brand,
#             "shipping": d["shipping"],
#             "shipping_percent": d["shipping_percent"]/n,
#             "finance": d["finance"],
#             "finance_percent": d["finance_percent"]/n,
#             "transport": d["transport"],
#             "transport_percent": d["transport_percent"]/n,
#             "reward": d["reward"],
#             "reward_percent": d["reward_percent"]/n,
#             "incentive": d["incentive"],
#             "incentive_percent": d["incentive_percent"]/n,
#             "customs": d["customs"],
#             "customs_": d["customs_percent"]/n,
#             "total_cost": d["total_cost"],
#             "total_selling": d["total_selling"],
#             "margin": d["margin"],
#             "margin_percent": d["margin_percent"]/n,
#         })


# ──────────────────────────────────────────────────────────────
# 3)  DOC-LEVEL TOTALS (was in JS calculate_total)
#     – extend as required
# ──────────────────────────────────────────────────────────────
def recalc_totals(doc):
    doc.total_shipping  = sum(it.total_shipping  or 0 for it in doc.items)
    doc.total_processing_charges = sum(it.total_processing_charges or 0 for it in doc.items)
    doc.total_reward    = sum(it.total_reward    or 0 for it in doc.items)
    doc.total_levee     = sum(it.total_levee     or 0 for it in doc.items)
    doc.total_std_margin= sum(it.total_std_margin or 0 for it in doc.items)

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
    """Ensure sum of child discounts matches parent discount amount"""
    parent_discount = doc.custom_discount_amount_value or 0
    total_row_discount = sum((row.custom_discount_amount_qty or 0) for row in doc.items)

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
            frappe.errprint(f"Overall margin for SP {salesperson} and brand {brand}: {overall}%")
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
