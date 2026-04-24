"""Bump custom_markup_ field precision to 6 decimals.

QN-FZCO-26-00151 reported: user typed Selling Price = 9000, saved, got
back 8999.9655 (display: 8999.97). Root cause was the Percent fieldtype
defaulting to 2 decimals of precision — the back-solved markup value
1027.5543 got truncated to 1027.5 on save, and applying that truncated
markup forward produced 8999.9655 instead of 9000.

Fix: set precision=6 on custom_markup_ for both Quotation Item and
Item Price. With 6 decimals, back-solve from 9000 → 1027.554323 and
forward calc reproduces 9000 to full precision, eliminating drift
independent of the drift-protection logic in run_calculation_pipeline.

Idempotent — safe to re-run.
"""

import frappe


_TARGETS = [
    ("Quotation Item", "custom_markup_"),
    ("Item Price", "custom_markup_"),
]


def execute():
    for dt, fieldname in _TARGETS:
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": dt, "fieldname": fieldname},
            ["name", "precision"],
            as_dict=True,
        )
        if not cf:
            print(f"[bump_custom_markup_precision] no Custom Field for {dt}.{fieldname} — skip")
            continue
        if cf.precision == "6":
            print(f"[bump_custom_markup_precision] {dt}.{fieldname} already precision=6 — skip")
            continue
        frappe.db.set_value("Custom Field", cf.name, "precision", "6", update_modified=False)
        print(f"[bump_custom_markup_precision] {dt}.{fieldname}: precision {cf.precision!r} → 6")

    frappe.db.commit()
    frappe.clear_cache()
