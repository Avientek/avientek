"""Sanity check for _batch_valuation_negative_result_guard in avientek/__init__.py
(I029021 / DN-LLC-26-01117 negative-valuation fix, ticket from Jithin 2026-09-01).

Read-only — no real documents touched. Exercises the exact function the live
patch runs against self.batch_avg_rate / self.stock_value_change right after
BatchNoValuation.calculate_avg_rate(), the same dict the two real callers read.

Run: bench --site <site> execute
     avientek.scripts.test_batch_valuation_negative_result_guard.run
"""
import frappe
from frappe.utils import flt
from avientek import _batch_valuation_negative_result_guard


def run():
    row = frappe.db.sql(
        """select item_code, warehouse, valuation_rate, stock_value, actual_qty
           from `tabBin` where valuation_rate > 0 and actual_qty > 5 and stock_value > 0
           limit 1""", as_dict=True)
    if not row:
        print("No suitable Bin found locally — cannot sanity-test."); return
    b = row[0]
    R, V, Q = flt(b.valuation_rate), flt(b.stock_value), flt(b.actual_qty)
    print(f"test item/wh: {b.item_code}/{b.warehouse}  bin rate={R} value={V} qty={Q}")

    # ---- Case 1: CORRUPTION — outward removes MORE value than exists,
    #      leaving units with negative value -> must clamp to Bin rate.
    out_qty = -(Q - 1)                     # leaves 1 unit
    inflated_change = -(V + 5000)          # removes way more than V exists
    s1 = frappe._dict(item_code=b.item_code, warehouse=b.warehouse,
                      batch_nos={"BN-X": frappe._dict(qty=out_qty)},
                      batch_avg_rate={"BN-X": abs(inflated_change / out_qty)},
                      stock_value_change=inflated_change,
                      sle=frappe._dict(actual_qty=out_qty, voucher_type="Delivery Note",
                                       voucher_no="TEST-NONEXISTENT", voucher_detail_no=None))
    _batch_valuation_negative_result_guard(s1)
    print(f"Case 1 (corruption) -> rate={s1.batch_avg_rate['BN-X']} change={s1.stock_value_change:.2f} "
          f"(expect rate==Bin {R}, change==R*out_qty, resulting value >= 0)")
    assert abs(s1.batch_avg_rate["BN-X"] - R) < 1e-6, "FAIL: did not clamp inflated rate to Bin rate"
    assert abs(s1.stock_value_change - R * out_qty) < 1e-3, "FAIL: stock_value_change not corrected"
    assert (V + s1.stock_value_change) >= -0.5, "FAIL: resulting value still negative after clamp"

    # ---- Case 2: NORMAL outward (leaves positive value) -> untouched.
    ok_qty, ok_rate = -2.0, R
    s2 = frappe._dict(item_code=b.item_code, warehouse=b.warehouse,
                      batch_nos={"BN-Y": frappe._dict(qty=ok_qty)},
                      batch_avg_rate={"BN-Y": ok_rate},
                      stock_value_change=ok_rate * ok_qty,
                      sle=frappe._dict(actual_qty=ok_qty, voucher_type="Delivery Note",
                                       voucher_no="TEST-NONEXISTENT", voucher_detail_no=None))
    _batch_valuation_negative_result_guard(s2)
    print(f"Case 2 (normal) -> rate={s2.batch_avg_rate['BN-Y']} (expect unchanged {ok_rate})")
    assert s2.batch_avg_rate["BN-Y"] == ok_rate, "FAIL: normal outward was altered"
    assert s2.stock_value_change == ok_rate * ok_qty, "FAIL: normal change altered"

    # ---- Case 3: INWARD -> untouched.
    s3 = frappe._dict(item_code=b.item_code, warehouse=b.warehouse,
                      batch_nos={"BN-Z": frappe._dict(qty=10.0)},
                      batch_avg_rate={"BN-Z": 99999.0}, stock_value_change=999990.0,
                      sle=frappe._dict(actual_qty=10.0, voucher_type="Purchase Receipt",
                                       voucher_no="TEST-NONEXISTENT", voucher_detail_no=None))
    _batch_valuation_negative_result_guard(s3)
    print(f"Case 3 (inward) -> rate={s3.batch_avg_rate['BN-Z']} (expect unchanged 99999.0)")
    assert s3.batch_avg_rate["BN-Z"] == 99999.0, "FAIL: inward altered"

    print("\n=== ALL CASES PASSED ===")
