import frappe
from frappe.utils import flt
from frappe.utils import flt, cint

@frappe.whitelist()
def get_last_transactions(customer, item_code):
    # Step 1: Get up to 5 Sales Invoices
    invoice_data = frappe.db.sql("""
        SELECT 'Sales Invoice' as doctype, si.name as name, sii.rate, si.posting_date as date
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON sii.parent = si.name
        WHERE si.customer = %s AND sii.item_code = %s AND si.docstatus = 1
        ORDER BY si.posting_date DESC
        LIMIT 5
    """, (customer, item_code), as_dict=True)

    invoice_count = len(invoice_data)
    remaining_count = 5 - invoice_count

    # Step 2: Get remaining Sales Orders if needed
    order_data = []
    if remaining_count > 0:
        order_data = frappe.db.sql("""
            SELECT 'Sales Order' as doctype, so.name as name, soi.rate, so.transaction_date as date
            FROM `tabSales Order Item` soi
            JOIN `tabSales Order` so ON soi.parent = so.name
            WHERE so.customer = %s AND soi.item_code = %s AND so.docstatus = 1
            ORDER BY so.transaction_date DESC
            LIMIT %s
        """, (customer, item_code, remaining_count), as_dict=True)

    # Step 3: Combine both
    combined_data = invoice_data + order_data

    return combined_data

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
def rebuild_brand_summary(doc):
    buckets = {}

    for it in doc.items:
        b = it.brand or "?"
        if b not in buckets:
            buckets[b] = {
                "shipping":0,"shipping_percent":0,
                "finance":0,"finance_percent":0,
                "transport":0,"transport_percent":0,
                "reward":0,"reward_percent":0,
                "incentive":0,"incentive_percent":0,
                "customs":0,"customs_percent":0,
                "total_cost":0,"total_selling":0,
                "margin":0,"margin_percent":0,
                "cnt":0,
            }

        bk = buckets[b]
        bk["shipping"]          += it.shipping
        bk["shipping_percent"]  += _to_flt(it.shipping_per)
        bk["finance"]           += it.custom_finance_value
        bk["finance_percent"]   += _to_flt(it.custom_finance_)
        bk["transport"]         += it.custom_transport_value
        bk["transport_percent"] += _to_flt(it.custom_transport_)
        bk["reward"]            += it.reward
        bk["reward_percent"]    += _to_flt(it.reward_per)
        bk["incentive"]         += it.custom_incentive_value
        bk["incentive_percent"] += _to_flt(it.custom_incentive_)
        bk["customs"]           += it.custom_customs_value
        bk["customs_percent"]   += _to_flt(it.custom_customs_)
        bk["total_cost"]        += it.custom_cogs
        bk["total_selling"]     += it.custom_selling_price
        bk["margin"]            += it.custom_markup_value
        bk["margin_percent"]    += it.custom_margin_
        bk["cnt"]               += 1

    doc.set("custom_brand_summary", [])
    for brand, d in buckets.items():
        n = d.pop("cnt") or 1
        doc.append("custom_brand_summary", {
            "brand": brand,
            "shipping": d["shipping"],
            "shipping_percent": d["shipping_percent"]/n,
            "finance": d["finance"],
            "finance_percent": d["finance_percent"]/n,
            "transport": d["transport"],
            "transport_percent": d["transport_percent"]/n,
            "reward": d["reward"],
            "reward_percent": d["reward_percent"]/n,
            "incentive": d["incentive"],
            "incentive_percent": d["incentive_percent"]/n,
            "customs": d["customs"],
            "customs_": d["customs_percent"]/n,
            "total_cost": d["total_cost"],
            "total_selling": d["total_selling"],
            "margin": d["margin"],
            "margin_percent": d["margin_percent"]/n,
        })


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


def get_avg_margin_percent_from_sales_orders(brand, salesperson):
    if not (brand and salesperson):
        return 0.0

    quotation_items = frappe.db.sql("""
        SELECT 
            so.name AS sales_order,
            qi.parent AS quotation,
            st.sales_person,
            soi.brand,
            qi.rate,
            qi.custom_cogs,
            qi.qty
        FROM `tabSales Order` so
        JOIN `tabSales Team` st ON st.parent = so.name
        JOIN `tabSales Order Item` soi ON soi.parent = so.name
        JOIN `tabQuotation Item` qi ON qi.parent = soi.prevdoc_docname AND qi.item_code = soi.item_code
        WHERE so.docstatus = 1
          AND st.sales_person = %(salesperson)s
          AND soi.brand = %(brand)s
          AND qi.brand = %(brand)s
          AND qi.rate > 0
    """, {
        "brand": brand,
        "salesperson": salesperson
    }, as_dict=True)

    if not quotation_items:
        return 0.0

    margins = []
    for row in quotation_items:
        rate = flt(row.rate)
        qty = flt(row.qty)
        total_cogs = flt(row.custom_cogs)
        cogs_per_unit = total_cogs / qty if qty else 0

        # if rate > 0 and cogs_per_unit >= 0:
        margin_percent = (rate - cogs_per_unit) / rate * 100
        frappe.errprint(f"[HISTORICAL MARGIN] SO: {row.sales_order}, Quotation: {row.quotation}, "
                            f"Salesperson: {row.sales_person}, Brand: {row.brand}, "
                            f"Rate: {rate}, Qty: {qty}, COGS: {total_cogs}, Margin: {margin_percent:.2f}%")
        margins.append(margin_percent)

    return sum(margins) / len(margins) if margins else 0.0


def validate_margin_for_workflow(doc, method):
    # if doc.docstatus == 1:
    #     return  # Skip already submitted docs

    salesperson = None
    if getattr(doc, "sales_team", None):
        salesperson = doc.sales_team[0].sales_person
    elif hasattr(doc, "sales_person"):
        salesperson = doc.sales_person

    requires_gm_approval = False
    requires_director_approval = False
    all_conditions_passed = True

    for row in doc.items:
        std_margin = flt(row.std_margin_per)
        margin_value= flt(row.custom_margin_)
        frappe.errprint(f"[VALIDATE MARGIN] Standard Margin: {std_margin}, Custom Margin: {margin_value}")
        custom_margin = flt(row.custom_margin_value or 0)
        frappe.errprint(f"[VALIDATE MARGIN] Custom Margin Value: {custom_margin}")
        selling_price = flt(row.custom_selling_price)

        # ✅ Condition 1: Margin ≥ Standard
        if margin_value >= std_margin:
            frappe.errprint("Condition 1 passed")
            continue

        # ✅ Condition 2: Avg margin from sales orders
        avg_margin = get_avg_margin_percent_from_sales_orders(row.brand, salesperson)
        frappe.errprint(avg_margin)
        if avg_margin >= std_margin:
            frappe.errprint("Condition 2 passed")
            continue

        # ❌ Both failed → Calculate how much below 20%
        all_conditions_passed = False
        margin_target = 0.2 * selling_price
        margin_diff = margin_target - custom_margin
        margin_percent_off = (margin_diff / margin_target) * 100 if margin_target else 0
        frappe.errprint(f"[VALIDATE MARGIN] Margin Percent Off: {margin_percent_off:.2f}%")
        if margin_percent_off <= 20:
            requires_gm_approval = True
        else:
            requires_director_approval = True

    # 🎯 Set next workflow state
    if all_conditions_passed:
        doc.custom_next_state = "Approved"
    elif requires_gm_approval:
        doc.custom_next_state = "Pending GM Approval"
    elif requires_director_approval:
        doc.custom_next_state = "Pending Director Approval"
    else:
        frappe.throw("Margin conditions not met.")
