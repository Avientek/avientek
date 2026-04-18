"""Make the Quotation Item "Selling Amount" field editable.

Finance wanted users to be able to type a target selling price directly
on a line; the client-side handler (custom_selling_price in
public/js/quotation.js) back-solves the markup % that reproduces that
selling price so the server recalc on save stays consistent with the
user's intent.
"""

import frappe


def execute():
    name = "Quotation Item-custom_selling_price"
    if frappe.db.exists("Custom Field", name):
        frappe.db.set_value("Custom Field", name, "read_only", 0, update_modified=False)
        frappe.db.commit()
        frappe.clear_cache(doctype="Quotation Item")
        print(f"[unlock_quotation_item_selling_price] {name} is now editable")
    else:
        print(f"[unlock_quotation_item_selling_price] {name} missing, skipping")
