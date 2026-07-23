"""Sanity check for the _patch_batch_valuation_zero_rate_safety_net
monkeypatch in avientek/__init__.py (MAT-STE-00774 / I030969 fix).

Read-only — no real documents touched.

IMPORTANT (rewritten 2026-07-23): the first version of this test called
`BatchNoValuation.get_incoming_rate()` directly. That method is NOT in
either of the two real call paths that persist a batch's rate
(`SerialAndBatchBundle.set_incoming_rate_for_outward_transaction` and
`stock_ledger.get_incoming_rate_for_serial_and_batch`, both of which read
`self.batch_avg_rate.get(batch_no)` directly) — so that test could pass
while the actual bug remained unfixed. This version instead exercises
`avientek._batch_valuation_zero_rate_guard`, the exact function the real
patch runs against `self.batch_avg_rate` / `self.stock_value_change` right
after `calculate_avg_rate()` populates them — the same dict both real
callers read from.

Run: bench --site <site> execute avientek.scripts.test_batch_valuation_zero_rate_guard.run
"""
import frappe
from avientek import _batch_valuation_zero_rate_guard


def _fake_state(item_code, warehouse, batch_no, qty, batch_avg_rate, stock_value_change,
                 actual_qty=None, voucher_type="Stock Entry", voucher_detail_no=None):
    fake = frappe._dict()
    fake.item_code = item_code
    fake.warehouse = warehouse
    fake.batch_nos = {batch_no: frappe._dict({"qty": qty})}
    fake.batch_avg_rate = {batch_no: batch_avg_rate}
    fake.stock_value_change = stock_value_change
    fake.sle = frappe._dict({
        "actual_qty": actual_qty if actual_qty is not None else qty,
        "voucher_type": voucher_type,
        "voucher_no": "TEST-NONEXISTENT",
        "voucher_detail_no": voucher_detail_no,
    })
    return fake


def run():
    row = frappe.db.sql(
        "select item_code, warehouse, valuation_rate from `tabBin` where valuation_rate > 0 limit 1",
        as_dict=True,
    )
    if not row:
        print("No Bin with positive valuation_rate found locally — cannot sanity-test.")
        return
    row = row[0]
    print(f"test item/wh: {row}")

    # Case 1: bug scenario — this batch's qty is outward, its own batch_avg_rate
    # resolved to 0, but the item genuinely holds real value right now.
    state1 = _fake_state(row.item_code, row.warehouse, "BATCH-A", qty=-46,
                          batch_avg_rate=0.0, stock_value_change=0.0)
    _batch_valuation_zero_rate_guard(state1)
    print(f"Case 1 (bug scenario) -> batch_avg_rate={state1.batch_avg_rate['BATCH-A']} "
          f"stock_value_change={state1.stock_value_change}  (expect rate > 0, matching Bin, "
          f"and stock_value_change == rate * -46)")
    assert state1.batch_avg_rate["BATCH-A"] > 0, "FAIL: safety net did not override the false zero"
    assert abs(state1.stock_value_change - state1.batch_avg_rate["BATCH-A"] * -46) < 1e-6, \
        "FAIL: stock_value_change wasn't corrected alongside batch_avg_rate"

    # Case 2: normal nonzero case must pass through untouched
    state2 = _fake_state(row.item_code, row.warehouse, "BATCH-B", qty=-2,
                          batch_avg_rate=241.9125, stock_value_change=-483.825)
    _batch_valuation_zero_rate_guard(state2)
    print(f"Case 2 (normal passthrough) -> {state2.batch_avg_rate['BATCH-B']}  (expect unchanged 241.9125)")
    assert state2.batch_avg_rate["BATCH-B"] == 241.9125, "FAIL: passthrough case was altered"
    assert state2.stock_value_change == -483.825, "FAIL: stock_value_change was altered on passthrough"

    # Case 3: inward transaction (positive qty) must NOT be touched
    state3 = _fake_state(row.item_code, row.warehouse, "BATCH-C", qty=48,
                          batch_avg_rate=0.0, stock_value_change=0.0, actual_qty=48)
    _batch_valuation_zero_rate_guard(state3)
    print(f"Case 3 (inward, untouched) -> {state3.batch_avg_rate['BATCH-C']}  (expect exactly 0.0)")
    assert state3.batch_avg_rate["BATCH-C"] == 0.0, "FAIL: inward transaction was altered"

    # Case 4: genuine zero-cost row (allow_zero_valuation_rate on the voucher item)
    # must NOT be overridden. Find a real submitted item row with that flag set,
    # so the DB lookup inside the guard has something real to find.
    zero_cost_row = frappe.db.sql(
        """select name from `tabStock Entry Detail` where allow_zero_valuation_rate = 1 limit 1""",
        as_dict=True,
    )
    if zero_cost_row:
        state4 = _fake_state(row.item_code, row.warehouse, "BATCH-D", qty=-3,
                              batch_avg_rate=0.0, stock_value_change=0.0,
                              voucher_type="Stock Entry", voucher_detail_no=zero_cost_row[0].name)
        _batch_valuation_zero_rate_guard(state4)
        print(f"Case 4 (allow_zero_valuation_rate) -> {state4.batch_avg_rate['BATCH-D']}  (expect exactly 0.0)")
        assert state4.batch_avg_rate["BATCH-D"] == 0.0, "FAIL: intentional zero-cost was overridden"
    else:
        print("Case 4 skipped — no Stock Entry Detail with allow_zero_valuation_rate=1 found locally.")

    print("\nAll sanity checks passed.")
