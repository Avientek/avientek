# Copyright (c) 2026, Avientek
"""#0510: classify warehouses by name into the customer's frozen categories
(RMA / Demo / Service / Repair / Reserved / In-Transit) vs sellable.
Read-only report to confirm the mapping before any data change."""
import re
import frappe

# Keyword -> category. Ordered; first match wins. Case-insensitive, matched
# against the warehouse name (word-ish boundaries where sensible).
PATTERNS = [
    ("RMA",        r"\brma\b"),
    ("Demo",       r"\bdemo\b|demonstration"),
    ("Service",    r"\bservice\b"),
    ("Repair",     r"\brepair\b"),
    ("Reserved",   r"\breserv"),                     # reserved / reservation
    ("In-Transit", r"in[\s\-_]*transit|\btransit\b|\bgit\b|goods in transit"),
]


def _cat(w):
    """Reserved is keyed off the explicit custom_is_reserved_warehouse flag
    (the RWH warehouses), which is far more reliable than the name. The other
    categories are matched by name."""
    if w.get("custom_is_reserved_warehouse"):
        return "Reserved"
    low = w["name"].lower()
    for cat, pat in PATTERNS:
        if re.search(pat, low):  # includes the Reserved name pattern (\breserv)
            return cat
    return None  # sellable


def run():
    whs = frappe.get_all("Warehouse", filters={"is_group": 0},
                         fields=["name", "warehouse_type", "company", "disabled",
                                 "custom_is_reserved_warehouse"])
    frozen, sellable = {}, []
    for w in whs:
        cat = _cat(w)
        if cat:
            frozen.setdefault(cat, []).append(w["name"])
        else:
            sellable.append(w["name"])
    # ticket proof: item I017971's stock warehouses must all end up sellable
    tick_whs = frappe.get_all("Bin", filters={"item_code": "I017971",
                              "actual_qty": [">", 0]}, pluck="warehouse")
    sset = set(sellable)
    print("TICKET I017971 stock warehouses -> sellable?")
    for w in tick_whs:
        print("   %-22s : %s" % (w, "SELLABLE (will show)" if w in sset else "still FROZEN"))
    print("total non-group warehouses:", len(whs))
    print("currently warehouse_type='Freezed Items':",
          sum(1 for w in whs if w["warehouse_type"] == "Freezed Items"))
    print("\n=== WOULD STAY FROZEN (match a category) ===")
    tot = 0
    for cat, _ in PATTERNS:
        names = sorted(frozen.get(cat, []))
        tot += len(names)
        print("  %-11s : %d" % (cat, len(names)))
        for n in names[:6]:
            print("       -", n)
        if len(names) > 6:
            print("       ... (+%d more)" % (len(names) - 6))
    print("  FROZEN TOTAL :", tot)
    print("\n=== WOULD BECOME SELLABLE (no category match) : %d ===" % len(sellable))
    for n in sorted(sellable)[:40]:
        print("   -", n)
    if len(sellable) > 40:
        print("   ... (+%d more)" % (len(sellable) - 40))
