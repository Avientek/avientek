import frappe


def execute():
    """Permanent fix for:
    1. Hide is_reverse_charge on Quotation
    2. Make custom_quote_type optional on Sales Invoice
    3. Fix Quotation Item field order (insert_after chain)
    """

    # 1. Hide is_reverse_charge on Quotation
    if frappe.db.exists("Custom Field", {"dt": "Quotation", "fieldname": "is_reverse_charge"}):
        frappe.make_property_setter({
            "doctype": "Quotation",
            "fieldname": "is_reverse_charge",
            "property": "hidden",
            "value": 1,
            "property_type": "Check",
        })

    # 2. Make custom_quote_type optional on Sales Invoice
    cf = frappe.db.exists("Custom Field", "Sales Invoice-custom_quote_type")
    if cf:
        frappe.db.set_value("Custom Field", cf, "reqd", 0)

    # 3. Fix Quotation Item insert_after chain for calculation fields
    insert_after_fixes = {
        # Col 1: percentages
        "shipping_per": "section_break_26",
        "reward_per": "shipping_per",
        "custom_finance_": "reward_per",
        "custom_transport_": "custom_finance_",
        # Col 2: values
        "shipping": "custom_transport_",
        "reward": "shipping",
        "custom_finance_value": "reward",
        "custom_transport_value": "custom_finance_value",
        # Col 3: calculation percentages
        "custom_column_break_calc_3": "custom_transport_value",
        "custom_incentive_": "custom_column_break_calc_3",
        "custom_customs_": "custom_incentive_",
        "custom_markup_": "custom_customs_",
        "custom_margin_": "custom_markup_",
        "custom_special_rate": "custom_margin_",
        "custom_discount_amount_value": "custom_special_rate",
        "custom_discount_amount_qty": "custom_discount_amount_value",
        # Col 4: calculation values
        "custom_incentive_value": "custom_discount_amount_qty",
        "custom_customs_value": "custom_incentive_value",
        "custom_markup_value": "custom_customs_value",
        "custom_margin_value": "custom_markup_value",
        "custom_selling_price": "custom_margin_value",
        "custom_total_": "custom_selling_price",
        "custom_cogs": "custom_total_",
        "custom_addl_discount_amount": "custom_cogs",
    }

    for fieldname, after in insert_after_fixes.items():
        name = f"Quotation Item-{fieldname}"
        if frappe.db.exists("Custom Field", name):
            frappe.db.set_value("Custom Field", name, "insert_after", after)

    frappe.db.commit()
