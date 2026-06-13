"""Fix wrong tax_category on "Output GST Out-state - AETPL".

Sridhar 2026-06-13 (during the LTD-26-27-00382 follow-up): the
Out-state template's `tax_category` was set to "Un Registered Regular"
— clearly a data-entry mistake; it should be "Out-State" to mirror the
In-state template's "In-State" pairing.

Consequence on prod: ERPNext's standard auto-resolution from
Tax Rule / Customer.tax_category can never route to Out-state because
no realistic customer has tax_category="Un Registered Regular".
Combined with the absence of Tax Rules for AETPL on prod (verified
2026-06-12), inter-state customers fell through to either empty taxes
(₹0 GST) or whatever template the user picked manually — frequently
wrong, producing the "Cannot charge CGST/SGST for inter-state
supplies" error.

This patch:
  1. Ensures the Tax Category "Out-State" exists.
  2. Sets the Out-state template's tax_category to "Out-State".
  3. Idempotent — re-running is a no-op.
"""

import frappe


_TEMPLATE_NAME = "Output GST Out-state - AETPL"
_TARGET_CATEGORY = "Out-State"


def execute():
    if not frappe.db.exists("Sales Taxes and Charges Template", _TEMPLATE_NAME):
        return

    current = frappe.db.get_value(
        "Sales Taxes and Charges Template", _TEMPLATE_NAME, "tax_category"
    )
    if current == _TARGET_CATEGORY:
        return

    if not frappe.db.exists("Tax Category", _TARGET_CATEGORY):
        # india_compliance ships "In-State" and "Out-State" Tax
        # Categories on a healthy install. If Out-State got deleted
        # somewhere along the line, recreate it minimally.
        cat = frappe.new_doc("Tax Category")
        cat.title = _TARGET_CATEGORY
        cat.insert(ignore_permissions=True)

    frappe.db.set_value(
        "Sales Taxes and Charges Template",
        _TEMPLATE_NAME,
        "tax_category",
        _TARGET_CATEGORY,
    )

    print(
        f"  -> {_TEMPLATE_NAME}.tax_category: {current!r} -> "
        f"{_TARGET_CATEGORY!r}"
    )
