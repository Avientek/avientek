"""Correct the Selling-Price editability setup (v2).

The first pass (unlock_quotation_item_selling_price) targeted the
wrong field — it unlocked custom_selling_price (label "Selling Amount",
the line total). Finance wanted custom_special_rate (label "Selling
Price", the per-unit rate) editable instead, so markup / margin can
cascade from a typed unit price.

This patch:
  - flips Quotation Item-custom_special_rate  read_only 1 -> 0
  - flips Quotation Item-custom_selling_price read_only 0 -> 1  (back to locked)

Idempotent — re-running does nothing if the flags are already correct.
Fresh module path so the Patch Log won't skip it.
"""

import frappe


_UNLOCK = "Quotation Item-custom_special_rate"
_RELOCK = "Quotation Item-custom_selling_price"


def execute():
    changed = False

    if frappe.db.exists("Custom Field", _UNLOCK):
        if frappe.db.get_value("Custom Field", _UNLOCK, "read_only") != 0:
            frappe.db.set_value("Custom Field", _UNLOCK, "read_only", 0, update_modified=False)
            changed = True
            print(f"[fix_quotation_item_selling_price_editable_v2] {_UNLOCK} -> editable")

    if frappe.db.exists("Custom Field", _RELOCK):
        if frappe.db.get_value("Custom Field", _RELOCK, "read_only") != 1:
            frappe.db.set_value("Custom Field", _RELOCK, "read_only", 1, update_modified=False)
            changed = True
            print(f"[fix_quotation_item_selling_price_editable_v2] {_RELOCK} -> read-only")

    if changed:
        frappe.db.commit()
        frappe.clear_cache(doctype="Quotation Item")
    else:
        print("[fix_quotation_item_selling_price_editable_v2] already correct")
