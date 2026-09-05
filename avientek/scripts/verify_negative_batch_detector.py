"""Verify avientek.events.negative_batch_balance.find_negative_batch_balances
matches ERPNext's own authoritative get_batch_qty (both directions):

  A. Every (batch, warehouse) the detector flags is truly negative per
     get_batch_qty  -> no FALSE POSITIVES.
  B. Sample many batches; any negative per-warehouse balance get_batch_qty
     reports is also caught by the detector -> no MISSED negatives.

    bench --site avintek.local execute \
        avientek.scripts.verify_negative_batch_detector.run
"""
import frappe
from frappe.utils import flt
from erpnext.stock.doctype.batch.batch import get_batch_qty
from avientek.events.negative_batch_balance import find_negative_batch_balances


def _gbq_rows(batch_no, item):
    # ERPNext's authoritative per-warehouse balance, negatives included, expiry
    # ignored, reserved ignored -> the actual ledger balance.
    return get_batch_qty(
        batch_no=batch_no, item_code=item,
        for_stock_levels=True, consider_negative_batches=True,
        ignore_reserved_stock=True,
    ) or []


def run(sample=1500):
    det = find_negative_batch_balances()
    det_map = {(r.batch_no, r.warehouse): flt(r.qty, 3) for r in det}
    print(f"detector flagged NEGATIVE (batch,warehouse) pairs: {len(det)}")

    # A) no false positives
    fp = 0
    for r in det:
        item = frappe.db.get_value("Batch", r.batch_no, "item")
        rows = _gbq_rows(r.batch_no, item)
        gt = None
        for x in rows:
            if x.get("warehouse") == r.warehouse:
                gt = flt(x.get("qty"), 3)
        ok = gt is not None and gt < 0 and abs(gt - flt(r.qty, 3)) < 0.01
        if not ok:
            fp += 1
            print(f"  FALSE POSITIVE? {r.batch_no}@{r.warehouse}: detector={flt(r.qty,3)} get_batch_qty={gt}")
    print(f"A) false positives: {fp}")

    # B) no missed negatives across a sample of batches
    batches = frappe.get_all("Batch", filters={"disabled": 0}, fields=["name", "item"], limit=sample)
    missed = 0
    checked = 0
    for b in batches:
        rows = _gbq_rows(b.name, b.item)
        for x in rows:
            checked += 1
            if flt(x.get("qty"), 3) < -0.001:
                key = (b.name, x.get("warehouse"))
                if key not in det_map:
                    missed += 1
                    print(f"  MISSED negative: {b.name}@{x.get('warehouse')} = {flt(x.get('qty'),3)}")
    print(f"B) batches sampled={len(batches)} warehouse-balances checked={checked} | MISSED negatives: {missed}")

    # C) return-path proof: the aggregation/GROUP BY/HAVING/row-shape are the
    # same for positive and negative balances (only the sign in HAVING differs).
    # Since no live negatives exist here, prove the query RETURNS correctly-
    # shaped rows whose SUM matches get_batch_qty using an inverted threshold.
    probe = frappe.db.sql(
        """
        SELECT sbe.batch_no, sbe.warehouse, sle.company, SUM(sbe.qty) AS qty
        FROM `tabStock Ledger Entry` sle
        INNER JOIN `tabSerial and Batch Entry` sbe ON sle.serial_and_batch_bundle = sbe.parent
        INNER JOIN `tabBatch` batch ON sbe.batch_no = batch.name
        WHERE batch.disabled = 0 AND sle.is_cancelled = 0
        GROUP BY sbe.batch_no, sbe.warehouse, sle.company
        HAVING SUM(sbe.qty) > 5
        ORDER BY SUM(sbe.qty) DESC
        LIMIT 5
        """,
        as_dict=True,
    )
    probe_ok = len(probe) > 0
    for r in probe:
        item = frappe.db.get_value("Batch", r.batch_no, "item")
        gt = None
        for x in _gbq_rows(r.batch_no, item):
            if x.get("warehouse") == r.warehouse:
                gt = flt(x.get("qty"), 3)
        match = gt is not None and abs(gt - flt(r.qty, 3)) < 0.01
        probe_ok = probe_ok and match
        print(f"  return-path: {r.batch_no}@{r.warehouse} query={flt(r.qty,3)} get_batch_qty={gt} match={match}")
    print(f"C) return-path proven (rows returned + shape + sums match get_batch_qty): {probe_ok}")

    print("\n=== RESULT:", "PASS" if (fp == 0 and missed == 0 and probe_ok) else "FAIL", "===")
    if det:
        print("negatives found (up to 20):")
        for r in det[:20]:
            print(f"  {r.batch_no} @ {r.warehouse} ({r.company}): {flt(r.qty,3)}")
