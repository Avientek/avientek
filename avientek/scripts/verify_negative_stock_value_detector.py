"""Structural regression check for the negative-stock-VALUE detector
(TSK-2026-00702). Read-only; asserts shape + threshold discipline (no dust
false positives), not specific data (which varies by restore).

    bench --site avintek.local execute \
        avientek.scripts.verify_negative_stock_value_detector.run
"""
from avientek.events.negative_batch_balance import (
    find_negative_stock_values,
    get_negative_stock_values,
    VALUE_TOLERANCE,
)
from frappe.utils import flt


def run():
    res = find_negative_stock_values()
    live, recent = res["live_bins"], res["recent_sles"]
    print(f"live_bins={len(live)} recent_sles={len(recent)} (tolerance={VALUE_TOLERANCE})")

    # 1) shape
    getter = get_negative_stock_values()
    ok_shape = all(k in getter for k in ("live_bin_count", "recent_sle_count", "live_bins", "recent_sles"))
    print("PASS getter shape:", ok_shape)

    # 2) threshold discipline — every flagged row is materially negative (no dust)
    ok_live = all(flt(b["stock_value"]) < -VALUE_TOLERANCE for b in live)
    ok_recent = all(flt(r["stock_value"]) < -VALUE_TOLERANCE for r in recent)
    print("PASS live rows all < -tol (no dust):", ok_live)
    print("PASS recent rows all < -tol (no dust):", ok_recent)

    # 3) recent rows carry the live/cosmetic tag
    ok_tag = all("current_bin_qty" in r for r in recent)
    print("PASS recent rows carry current_bin_qty tag:", ok_tag)

    # 4) discriminating: a huge tolerance must return nothing (proves filtering,
    #    not a query that always returns rows)
    none_res = find_negative_stock_values(threshold=10**12)
    ok_filter = not none_res["live_bins"] and not none_res["recent_sles"]
    print("PASS threshold filter works (huge tol -> empty):", ok_filter)

    all_ok = ok_shape and ok_live and ok_recent and ok_tag and ok_filter
    print("\n=== RESULT:", "PASS" if all_ok else "FAIL", "===")
    if recent:
        print("sample recent negatives (item @ wh | bal | current_bin_qty):")
        for r in recent[:8]:
            print(f"  {r['item_code']} @ {r['warehouse']} | {flt(r['stock_value'],2)} | qty={flt(r['current_bin_qty'],3)}")
