# Copyright (c) 2026, Avientek
"""#0510 (SUP): Quotation "Stock Availability" panel shows nothing.

get_company_stock() (avientek/events/quotation.py) hides warehouses whose
`warehouse_type = "Freezed Items"` from the quote stock indicator (RMA / Demo /
Service / Repair / Reserved / In-Transit stock is not for sale). A data error
tagged EVERY warehouse (all 138) with warehouse_type = "Freezed Items", so the
panel had nothing left to show for any item.

Customer rule (Avientek / orders.mea, 2026): keep ONLY RMA / Demo / Service /
Repair / Reserved / In-Transit warehouses frozen; treat all others as sellable.

This patch clears warehouse_type (Freezed Items -> NULL) on every currently
frozen warehouse that does NOT match one of those categories, so the sellable
ones start showing in the quote stock panel again. The frozen categories are
left as "Freezed Items" (still excluded, as intended).

Category detection:
  - Reserved: the explicit `custom_is_reserved_warehouse` flag (the RWH
    warehouses) OR the name — the flag is the authoritative signal.
  - RMA / Demo / Service / Repair / In-Transit: matched by warehouse name.

Idempotent: only warehouses still tagged "Freezed Items" are considered, and
only non-matching ones are cleared, so re-running changes nothing further.
"""
import re
import frappe

_PATTERNS = [
    ("RMA",        r"\brma\b"),
    ("Demo",       r"\bdemo\b|demonstration"),
    ("Service",    r"\bservice\b"),
    ("Repair",     r"\brepair\b"),
    ("Reserved",   r"\breserv"),
    ("In-Transit", r"in[\s\-_]*transit|\btransit\b|\bgit\b|goods in transit"),
]

FROZEN_TYPE = "Freezed Items"


def _should_stay_frozen(name, is_reserved_flag):
    if is_reserved_flag:
        return "Reserved"
    low = (name or "").lower()
    for cat, pat in _PATTERNS:
        if re.search(pat, low):
            return cat
    return None


def execute():
    # Only leaf (non-group) warehouses hold stock and feed get_company_stock;
    # group warehouses' type is irrelevant to the quote panel, so leave them.
    rows = frappe.get_all(
        "Warehouse",
        filters={"warehouse_type": FROZEN_TYPE, "is_group": 0},
        fields=["name", "custom_is_reserved_warehouse"],
    )
    if not rows:
        return

    to_clear, kept = [], 0
    for w in rows:
        if _should_stay_frozen(w["name"], w.get("custom_is_reserved_warehouse")):
            kept += 1
        else:
            to_clear.append(w["name"])

    for name in to_clear:
        # set to NULL — get_company_stock's SQL explicitly includes NULL-typed
        # warehouses (WHERE warehouse_type IS NULL OR != 'Freezed Items').
        frappe.db.set_value("Warehouse", name, "warehouse_type", None,
                            update_modified=False)

    frappe.db.commit()
    frappe.logger().info(
        "reclassify_freezed_warehouses: kept %d frozen, cleared %d to sellable"
        % (kept, len(to_clear))
    )
