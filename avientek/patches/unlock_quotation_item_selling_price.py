"""Make the Quotation Item "Selling Price" (per-unit, custom_special_rate)
field editable, and keep "Selling Amount" (total, custom_selling_price)
read-only.

Finance asked for the per-unit rate to be directly type-able so they can
price a single unit and let markup / margin / line total cascade. The
client-side handler (custom_special_rate in public/js/quotation.js)
back-solves the markup % that reproduces the typed per-unit price when
multiplied by qty, so the server's calc_item_totals stays consistent
with the user's intent on save.
"""

import frappe


_UNLOCK = "Quotation Item-custom_special_rate"
_RELOCK = "Quotation Item-custom_selling_price"


def execute():
    changed = False
    if frappe.db.exists("Custom Field", _UNLOCK):
        current = frappe.db.get_value("Custom Field", _UNLOCK, "read_only")
        if current != 0:
            frappe.db.set_value("Custom Field", _UNLOCK, "read_only", 0, update_modified=False)
            changed = True
            print(f"[unlock_quotation_item_selling_price] {_UNLOCK} -> editable")
        else:
            print(f"[unlock_quotation_item_selling_price] {_UNLOCK} already editable")
    else:
        print(f"[unlock_quotation_item_selling_price] {_UNLOCK} missing, skipping")

    if frappe.db.exists("Custom Field", _RELOCK):
        current = frappe.db.get_value("Custom Field", _RELOCK, "read_only")
        if current != 1:
            frappe.db.set_value("Custom Field", _RELOCK, "read_only", 1, update_modified=False)
            changed = True
            print(f"[unlock_quotation_item_selling_price] {_RELOCK} -> read-only")

    if changed:
        frappe.db.commit()
        frappe.clear_cache(doctype="Quotation Item")
