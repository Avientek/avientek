import frappe


def execute():
    """Fix 4-column calculation layout for Quotation Item.

    1. Create missing column breaks (custom_column_break_calc_3/4)
    2. Hide legacy fields (levee, processing_charges, std_margin, etc.)
    3. Fix insert_after chain AND idx ordering for correct 4-column layout
    4. Hide stale column breaks (37, 38, 44)
    """
    dt = "Quotation Item"

    # ── Step 1: Create missing column breaks ──
    column_breaks = [
        {"fieldname": "custom_column_break_calc_3", "insert_after": "custom_transport_value"},
        {"fieldname": "custom_column_break_calc_4", "insert_after": "custom_discount_amount_qty"},
    ]
    for cb in column_breaks:
        if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": cb["fieldname"]}):
            doc = frappe.new_doc("Custom Field")
            doc.dt = dt
            doc.fieldname = cb["fieldname"]
            doc.fieldtype = "Column Break"
            doc.insert_after = cb["insert_after"]
            doc.hidden = 0
            doc.insert()
            print(f"CREATED: {cb['fieldname']}")
        else:
            print(f"EXISTS: {cb['fieldname']}")

    # ── Step 2: Hide legacy fields ──
    legacy_fields = [
        "levee_per", "levee", "total_levee", "base_levee",
        "processing_charges_per", "processing_charges",
        "total_processing_charges", "base_processing_charges",
        "std_margin_per", "std_margin", "total_std_margin", "base_std_margin",
        "total_shipping", "total_reward",
        "base_shipping", "base_reward",
        # Stale column breaks that disrupt layout
        "column_break_37", "column_break_38", "column_break_44",
    ]
    for fn in legacy_fields:
        cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fn}, "name")
        if cf:
            frappe.db.set_value("Custom Field", cf, "hidden", 1)
            print(f"HIDDEN: {fn}")

    # ── Step 3: Fix insert_after chain AND idx for 4-column layout ──
    #
    # Col 1 (%)          Col 2 (Values)       Col 3 (Calc %)              Col 4 (Calc Values)
    # section_break_26   column_break_32      custom_column_break_calc_3  custom_column_break_calc_4
    # shipping_per       shipping             custom_incentive_           custom_incentive_value
    # reward_per         reward               custom_customs_             custom_customs_value
    # custom_finance_    custom_finance_value  custom_markup_              custom_markup_value
    # custom_transport_  custom_transport_val  custom_margin_              custom_margin_value
    #                                          custom_special_rate         custom_selling_price
    #                                          custom_discount_amt_value   custom_total_
    #                                          custom_discount_amt_qty     custom_cogs
    chain = [
        # Col 1: percentages
        ("section_break_26", None),
        ("shipping_per", "section_break_26"),
        ("reward_per", "shipping_per"),
        ("custom_finance_", "reward_per"),
        ("custom_transport_", "custom_finance_"),
        # Col 2: values
        ("column_break_32", "custom_transport_"),
        ("shipping", "column_break_32"),
        ("reward", "shipping"),
        ("custom_finance_value", "reward"),
        ("custom_transport_value", "custom_finance_value"),
        # Col 3: calculation percentages
        ("custom_column_break_calc_3", "custom_transport_value"),
        ("custom_incentive_", "custom_column_break_calc_3"),
        ("custom_customs_", "custom_incentive_"),
        ("custom_markup_", "custom_customs_"),
        ("custom_margin_", "custom_markup_"),
        ("custom_special_rate", "custom_margin_"),
        ("custom_discount_amount_value", "custom_special_rate"),
        ("custom_discount_amount_qty", "custom_discount_amount_value"),
        # Col 4: calculation values
        ("custom_column_break_calc_4", "custom_discount_amount_qty"),
        ("custom_incentive_value", "custom_column_break_calc_4"),
        ("custom_customs_value", "custom_incentive_value"),
        ("custom_markup_value", "custom_customs_value"),
        ("custom_margin_value", "custom_markup_value"),
        ("custom_selling_price", "custom_margin_value"),
        ("custom_total_", "custom_selling_price"),
        ("custom_cogs", "custom_total_"),
    ]

    # Get the idx of section_break_26 as starting point
    start_idx = frappe.db.get_value(
        "Custom Field",
        {"dt": dt, "fieldname": "section_break_26"},
        "idx",
    ) or 33

    for i, (fieldname, after) in enumerate(chain):
        cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "name")
        if cf:
            updates = {"idx": start_idx + i}
            if after is not None:
                updates["insert_after"] = after
            frappe.db.set_value("Custom Field", cf, updates)
            print(f"SET: {fieldname} idx={start_idx + i}" + (f" after={after}" if after else ""))
        else:
            print(f"SKIP: {fieldname} (not a Custom Field)")

    frappe.db.commit()
    print("DONE: Quotation Item 4-column layout fixed.")
