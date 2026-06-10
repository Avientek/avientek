"""Sridhar/Rahul 2026-06-09 — make Quotation.customer_name pickable in
Report View (and visible read-only on the form).

ERPNext ships Quotation.customer_name with hidden=1 because the value is
auto-fetched from party_name. But Frappe's Pick Columns picker filters
out fields where hidden=1 OR report_hide=1, so the customer-friendly
name was unreachable from the Quote report — only "Customer Address" /
"Customer Group" surfaced under a "customer" search.

Fix via two Property Setters:
  - hidden = 0       → field appears in Pick Columns and on the form
  - read_only = 1    → still safe on the form; users can't accidentally
                       overwrite the auto-fetched value

Idempotent — make_property_setter overwrites if present.
"""

import frappe


def execute():
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter

    DOCTYPE = "Quotation"
    FIELD = "customer_name"

    make_property_setter(
        DOCTYPE, FIELD, "hidden", "0", "Check",
        validate_fields_for_doctype=False,
    )
    make_property_setter(
        DOCTYPE, FIELD, "read_only", "1", "Check",
        validate_fields_for_doctype=False,
    )
    frappe.db.commit()
    frappe.clear_cache(doctype=DOCTYPE)
    print(f"[expose_customer_name_in_quote_report] Quotation.customer_name: "
          f"hidden=0 + read_only=1 — now pickable in Pick Columns.")
