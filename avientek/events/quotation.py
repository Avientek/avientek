import frappe
from frappe.utils import flt
from frappe.utils import flt, cint
from frappe.model.workflow import apply_workflow


@frappe.whitelist()
def get_last_transactions(customer, item_code):
    # Step 1: Get up to 5 submitted Sales Invoices
    invoice_data = frappe.db.sql("""
        SELECT 'Sales Invoice' AS doctype, si.name AS name, sii.rate, si.posting_date AS date,
               sii.sales_order
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON sii.parent = si.name
        WHERE si.customer = %s AND sii.item_code = %s AND si.docstatus = 1
        ORDER BY si.posting_date DESC
        LIMIT 5
    """, (customer, item_code), as_dict=True)

    # Step 2: Get Sales Orders that have never been invoiced (draft or submitted)
    # Find all orders already linked to invoices
    invoiced_orders = frappe.db.sql("""
        SELECT DISTINCT sii.sales_order
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON sii.parent = si.name
        WHERE si.customer = %s AND sii.item_code = %s
          AND sii.sales_order IS NOT NULL
    """, (customer, item_code))
    invoiced_orders = {row[0] for row in invoiced_orders if row[0]}

    remaining_count = 5 - len(invoice_data)
    order_data = []

    if remaining_count > 0:
        order_data = frappe.db.sql("""
            SELECT 'Sales Order' AS doctype, so.name AS name, soi.rate, so.transaction_date AS date
            FROM `tabSales Order Item` soi
            JOIN `tabSales Order` so ON soi.parent = so.name
            WHERE so.customer = %(customer)s
              AND soi.item_code = %(item_code)s
              AND so.docstatus = 1
              AND so.name NOT IN %(exclude_orders)s
            ORDER BY so.transaction_date DESC
            LIMIT %(limit)s
        """, {
            "customer": customer,
            "item_code": item_code,
            "exclude_orders": tuple(invoiced_orders) if invoiced_orders else ("",),
            "limit": remaining_count
        }, as_dict=True)

    # Step 3: Combine
    combined_data = invoice_data + order_data

    # Step 4: If no invoices at all, just show orders without invoices
    if not invoice_data:
        combined_data = frappe.db.sql("""
            SELECT 'Sales Order' AS doctype, so.name AS name, soi.rate, so.transaction_date AS date
            FROM `tabSales Order Item` soi
            JOIN `tabSales Order` so ON soi.parent = so.name
            WHERE so.customer = %(customer)s
              AND soi.item_code = %(item_code)s
              AND so.docstatus = 1
              AND so.name NOT IN %(exclude_orders)s
            ORDER BY so.transaction_date DESC
            LIMIT 5
        """, {
            "customer": customer,
            "item_code": item_code,
            "exclude_orders": tuple(invoiced_orders) if invoiced_orders else ("",)
        }, as_dict=True)

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



# -*- coding: utf-8 -*-
"""
Compute two Boolean flags on Quotation so that Workflow conditions
need only read doc.auto_approve_ok / doc.gm_approve_ok.
"""


# ------------------------------------------------------------------ #
#  Helper functions — you already wrote these
# ------------------------------------------------------------------ #
def rule_1_or_2_pass(doc):
    """Return True when either margin Rule 1 or Rule 2 passes."""
    salesperson = (
        doc.sales_team[0].sales_person
        if doc.get("sales_team")
        else doc.get("sales_person")
    )

    # --------------- helper for Rule 2 ------------------
    def avg_margin(brand):
        if not (brand and salesperson):
            frappe.errprint(f"Brand {brand} or salesperson missing → avg_margin = 0")
            return 0
        date_cut = frappe.db.get_single_value(
            "Selling Settings", "custom_applicable_date"
        )
        frappe.errprint(f"Brand {brand} salesperson {salesperson} date_cut {date_cut}")
        cond = """
            so.docstatus = 1
            AND st.sales_person = %(sp)s
            AND soi.brand = %(br)s
            AND qi.rate > 0
        """
        if date_cut:
            cond += " AND so.transaction_date >= %(dc)s"

        rows = frappe.db.sql(
            f"""
            SELECT qi.rate, qi.custom_cogs, qi.qty
              FROM `tabSales Order` so
              JOIN `tabSales Team` st  ON st.parent = so.name
              JOIN `tabSales Order Item` soi ON soi.parent = so.name
              JOIN `tabQuotation Item`  qi
                    ON qi.parent      = soi.prevdoc_docname
                   AND qi.item_code   = soi.item_code
             WHERE {cond}
            """,
            {"sp": salesperson, "br": brand, "dc": date_cut},
            as_dict=True,
        )
        frappe.errprint(f"Brand {brand} salesperson {salesperson} rows: {rows}")
        if not rows:
            frappe.errprint(f"No previous sales orders found for Brand: {brand}")
            return 0
        margins = [
            # (flt(r.rate) - flt(r.custom_cogs) / flt(r.qty or 1)) / flt(r.rate) * 100
            ((flt(r.rate) - (flt(r.custom_cogs) / flt(r.qty or 1))) / flt(r.rate)) * 100

            for r in rows
        ]
        frappe.errprint(f"Brand {brand} margins: {margins}")
        frappe.errprint(f"Brand {brand} margins: {sum(margins) / len(margins)}")
        return sum(margins) / len(margins)

    # --------------- apply rules over all items ----------
    for row in doc.items:
        std = flt(row.std_margin_per)
        frappe.errprint(f"Checking item {row.item_code} (Brand: {row.brand}) → Std Margin: {std}, Item Margin: {row.custom_margin_}")

        if flt(row.custom_margin_) >= std:
            frappe.errprint(f"Rule 1 passed for item {row.item_code} → Item Margin: {row.custom_margin_} >= Std Margin: {std}")# Rule 1
            return True
        brand_avg_margin = avg_margin(row.brand)
        if brand_avg_margin >= std:
            frappe.errprint(f"Rule 2 passed for item {row.item_code} → Avg Margin: {brand_avg_margin} >= Std Margin: {std}")
            return True
        frappe.errprint(f"No rule passed for item {row.item_code}")
    return False


def rule_3_pass(doc):
    """Return True if GM is allowed to approve the quotation."""
    for row in doc.items:
        target = 0.20 * flt(row.custom_selling_price)
        diff   = target - flt(row.custom_margin_value or 0)
        if target and (diff / target) * 100 > 20:
            frappe.errprint(f"Rule 3 failed for item {row.item_code} → {diff / target * 100}% below target margin")
            return False
    frappe.errprint("Rule 3 passed for all items")

    return True


# ------------------------------------------------------------------ #
#                Doc-event hook – called on validate
# ------------------------------------------------------------------ #
def set_margin_flags(doc, method=None):
    """
    Compute & store the two Booleans so Workflow can read them
    without evaluating Python in the Condition column.
    """
    doc.custom_auto_approve_ok = 1 if rule_1_or_2_pass(doc) else 0
    doc.custom_gm_approve_ok   = 1 if rule_3_pass(doc)      else 0
