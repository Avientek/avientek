"""Sridhar 2026-07-23: scope check for the DN-AT-26-00397 / Item I024926
valuation glitch (client-reported "Valuation Rate 5,805.90" on Stock
Balance for Stores - KSA).

Root cause confirmed via avientek.scripts.diag_stock_valuation_i024926:
the Delivery Note's outward Serial and Batch Entry for batch BN17455
was persisted with incoming_rate=0 even though that batch had a real
positive receipt value moments earlier (GRN-KSA-26-00129). Re-running
ERPNext's own BatchNoValuation right now, on the same data, computes
the CORRECT rate (241.9125) for that same batch — so this isn't a bug
in the valuation math itself, it's stale/wrong data from whatever ran
at submit time (likely a transaction-visibility race between two
transactions landing seconds apart).

This script is read-only. It finds every OTHER outward Serial and
Batch Entry system-wide with incoming_rate = 0 (or NULL) for a batch
that demonstrably has real inward value elsewhere, i.e. the same
symptom, so we know whether this is a one-off or a recurring pattern
before deciding what to do about it (a targeted Repost Item Valuation
per affected item+warehouse — a financial correction, needs sammish's
sign-off — vs. something systemic worth raising with ERPNext/reviewing
job-queue concurrency for).

Output: CSV in sites/<site>/private/files/ (not in version control).

Run: bench --site avientek.localhost execute avientek.scripts.diag_zero_rate_outward_batches.run
"""
import csv
import os
import frappe
from frappe.utils import now_datetime


def run():
    suspects = frappe.db.sql(
        """
        SELECT sle.name AS sle_name, sle.item_code, sle.warehouse,
               sle.voucher_type, sle.voucher_no, sle.posting_date, sle.posting_time,
               sbe.batch_no, sbe.qty, sbe.incoming_rate, sbe.parent AS bundle
        FROM `tabSerial and Batch Entry` sbe
        INNER JOIN `tabStock Ledger Entry` sle ON sle.serial_and_batch_bundle = sbe.parent
        WHERE sle.is_cancelled = 0
          AND sbe.qty < 0
          AND (sbe.incoming_rate IS NULL OR sbe.incoming_rate = 0)
          AND sbe.batch_no IS NOT NULL AND sbe.batch_no != ''
        """,
        as_dict=True,
    )

    if not suspects:
        print("No zero-rate outward batch entries found system-wide.")
        return

    batch_nos = list({s.batch_no for s in suspects})
    inward_by_batch = {}
    if batch_nos:
        placeholders = ", ".join(["%s"] * len(batch_nos))
        inward_rows = frappe.db.sql(
            f"""
            SELECT sbe.batch_no,
                   SUM(sbe.qty) AS in_qty,
                   SUM(sbe.qty * COALESCE(sbe.incoming_rate, 0)) AS in_value
            FROM `tabSerial and Batch Entry` sbe
            INNER JOIN `tabStock Ledger Entry` sle ON sle.serial_and_batch_bundle = sbe.parent
            WHERE sle.is_cancelled = 0 AND sbe.qty > 0 AND sbe.batch_no IN ({placeholders})
            GROUP BY sbe.batch_no
            """,
            batch_nos, as_dict=True,
        )
        inward_by_batch = {r.batch_no: r for r in inward_rows}

    flagged = []
    for s in suspects:
        inward = inward_by_batch.get(s.batch_no)
        if inward and inward.in_qty and inward.in_value and (inward.in_value / inward.in_qty) > 0.01:
            flagged.append((s, inward))

    if not flagged:
        print(f"{len(suspects)} zero-rate outward rows found, but none belong to a batch "
              f"with a real positive receipt value — likely genuine zero-cost items.")
        return

    private = frappe.get_site_path("private", "files")
    os.makedirs(private, exist_ok=True)
    ts = now_datetime().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(private, f"zero_rate_outward_batches_{ts}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Item Code", "Warehouse", "Batch No", "Voucher Type", "Voucher #",
                    "Posting Date", "Posting Time", "Outward Qty", "Persisted Rate",
                    "Expected Rate (from real receipts)", "Bundle"])
        for s, inward in flagged:
            expected_rate = inward.in_value / inward.in_qty
            w.writerow([
                s.item_code, s.warehouse, s.batch_no, s.voucher_type, s.voucher_no,
                s.posting_date, s.posting_time, s.qty, s.incoming_rate,
                f"{expected_rate:.4f}", s.bundle,
            ])

    print(f"[diag_zero_rate_outward_batches] scanned {len(suspects)} zero-rate outward rows, "
          f"{len(flagged)} confirmed wrong (batch had real receipt value) — csv={path}")
    for s, inward in flagged[:20]:
        expected_rate = inward.in_value / inward.in_qty
        print(f"  {s.voucher_type} {s.voucher_no}  item={s.item_code} wh={s.warehouse} "
              f"batch={s.batch_no}  qty={s.qty}  persisted_rate={s.incoming_rate}  "
              f"expected_rate~{expected_rate:.4f}")
