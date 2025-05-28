import frappe
from frappe.utils import flt

def get_previous_margins_from_related_quotations(current_quotation, brand, salesperson):
    if not (brand and salesperson):
        return []

    # Step 1: Find sales orders created from this quotation
    linked_sales_orders = frappe.get_all(
        "Sales Order",
        filters={"prevdoc_docname": current_quotation},
        fields=["name"]
    )

    if not linked_sales_orders:
        return []

    sales_order_names = [so.name for so in linked_sales_orders]

    # Step 2: Find other quotations linked to those sales orders
    related_quotations = frappe.get_all(
        "Sales Order",
        filters={"name": ["in", sales_order_names]},
        fields=["prevdoc_docname"]
    )

    quotation_names = [q.prevdoc_docname for q in related_quotations if q.prevdoc_docname != current_quotation]

    if not quotation_names:
        return []

    # Step 3: Fetch margins from those other quotations with same brand and salesperson
    results = frappe.db.sql("""
        SELECT qi.custom_margin_
        FROM `tabQuotation` q
        JOIN `tabQuotation Item` qi ON qi.parent = q.name
        JOIN `tabSales Team` st ON st.parent = q.name
        WHERE q.name IN %(quotation_names)s
          AND qi.brand = %(brand)s
          AND st.sales_person = %(salesperson)s
          AND q.docstatus < 2
    """, {
        "quotation_names": quotation_names,
        "brand": brand,
        "salesperson": salesperson
    }, as_dict=True)

    return [flt(row.custom_margin_) for row in results]

def validate_margin_before_submit(doc, method):
    margins_failed = []
    brand_std_map = {}

    for row in doc.items:
        brand = row.brand
        std_margin = flt(row.std_margin_per)
        item_margin = flt(row.custom_margin_ or 0)

        brand_std_map[brand] = std_margin

        if item_margin < std_margin:
            margins_failed.append((brand, std_margin, item_margin))

    # Condition 1 — All margins are OK
    if not margins_failed:
        doc.workflow_state = "Approved"
        return

    # Get salesperson
    salesperson = None
    if getattr(doc, "sales_team", None):
        salesperson = doc.sales_team[0].sales_person
    elif hasattr(doc, "sales_person"):
        salesperson = doc.sales_person

    # Condition 2 — Check previous quotations' margins
    for brand, std_margin, item_margin in margins_failed:
        prev_margins = get_previous_margins_from_related_quotations(doc.name, brand, salesperson)
        if any(prev < std_margin for prev in prev_margins):
            doc.workflow_state = "Dept Head Approved"
            frappe.throw(
                f"Margin for brand '{brand}' is below standard ({std_margin}%).\n"
                f"Previous quotation also had low margin for same brand and salesperson.\n"
                f"Dept Head approval required. Cannot submit."
            )

    # Condition 3 — Critical margin drop (below 80% of standard)
    for brand, std_margin, item_margin in margins_failed:
        if item_margin < (std_margin * 0.80):
            doc.workflow_state = "BU Head Approved"
            frappe.throw(
                f"Margin for brand '{brand}' is critically low ({item_margin}%).\n"
                f"BU Head approval required. Cannot submit."
            )

    # If all else passes
    doc.workflow_state = "Dept Head Submitted"
