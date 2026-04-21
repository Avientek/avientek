"""Re-assert Selling Price editability in Draft (v3).

v2 targeted the same fields but may have been skipped in production
(Patch Log already flagged the v1 module path). Fresh module path forces
it to run again. Same intent:

  - Quotation Item-custom_special_rate  (per-unit "Selling Price") → editable
  - Quotation Item-custom_selling_price (line total "Selling Amount") → read-only

Business rule: Selling Price must be editable until the Quotation is
finally submitted (Approved state). After submit the field is locked
by allow_on_submit=0 (intentional).

Idempotent — re-runs do nothing if flags already correct.
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
            print(f"[v3] {_UNLOCK} -> editable")

    if frappe.db.exists("Custom Field", _RELOCK):
        if frappe.db.get_value("Custom Field", _RELOCK, "read_only") != 1:
            frappe.db.set_value("Custom Field", _RELOCK, "read_only", 1, update_modified=False)
            changed = True
            print(f"[v3] {_RELOCK} -> read-only")

    if changed:
        frappe.db.commit()
        frappe.clear_cache(doctype="Quotation Item")
    else:
        print("[v3] already correct — no-op")
