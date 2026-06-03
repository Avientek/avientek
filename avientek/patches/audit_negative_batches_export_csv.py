"""Patch A1 — audit current negative-batch buckets and export CSV.

Sridhar 2026-06-03: read-only snapshot to capture the state of negative
batches BEFORE cleanup runs. Output goes to sites/<site>/private/files/
so it's downloadable from /app/file but not in version control.

Re-runnable any time. Each run overwrites with a fresh timestamp file
so historical snapshots are preserved by filename.
"""
import csv
import os
import frappe
from frappe.utils import now_datetime


def execute():
	# TRUE per-batch balance combines two sources to avoid the same
	# upstream ERPNext bug we're trying to fix:
	#   (a) Legacy SLEs that carry batch_no on the row AND have no SBB
	#       attached (older transactions / non-SBB items).
	#   (b) SBE.qty rows on Serial and Batch Bundles linked from
	#       SBB-using SLEs (modern v15 transactions).
	# Summing BOTH for the same SLE would double-count (the upstream
	# get_stock_ledgers_batches bug). Excluding the SBB-linked rows from
	# the legacy query keeps it correct.
	#
	# Identify all (item, warehouse, batch) combos across both sources,
	# then compute the true balance for each.
	rows = frappe.db.sql(
		"""
		SELECT
			x.item_code, x.warehouse, x.batch_no,
			SUM(x.qty)         AS balance,
			SUM(x.value_diff)  AS value_diff
		FROM (
			SELECT sle.item_code, sle.warehouse, sle.batch_no,
			       sle.actual_qty AS qty,
			       sle.stock_value_difference AS value_diff
			FROM `tabStock Ledger Entry` sle
			WHERE sle.is_cancelled = 0
			  AND sle.batch_no IS NOT NULL AND sle.batch_no != ''
			  AND (sle.serial_and_batch_bundle IS NULL OR sle.serial_and_batch_bundle = '')
			UNION ALL
			SELECT sle.item_code, sle.warehouse, sbe.batch_no,
			       sbe.qty,
			       /* SBE doesn't carry stock_value_difference per row;
			          we approximate by qty * SBE.incoming_rate. For Outward
			          rows this is the consumed value; for Inward, received. */
			       (sbe.qty * COALESCE(sbe.incoming_rate, 0)) AS value_diff
			FROM `tabSerial and Batch Entry` sbe
			INNER JOIN `tabStock Ledger Entry` sle
			    ON sle.serial_and_batch_bundle = sbe.parent
			WHERE sle.is_cancelled = 0
			  AND sbe.batch_no IS NOT NULL AND sbe.batch_no != ''
		) x
		GROUP BY x.item_code, x.warehouse, x.batch_no
		HAVING SUM(x.qty) < -0.0001
		ORDER BY value_diff ASC
		""",
		as_dict=True,
	)

	# Resolve warehouse -> company once
	wh_to_co = {
		w["name"]: w["company"]
		for w in frappe.get_all("Warehouse", fields=["name", "company"])
	}

	# Write CSV to private/files
	private = frappe.get_site_path("private", "files")
	os.makedirs(private, exist_ok=True)
	ts = now_datetime().strftime("%Y%m%d_%H%M%S")
	path = os.path.join(private, f"negative_batches_audit_{ts}.csv")
	with open(path, "w", newline="") as f:
		w = csv.writer(f)
		w.writerow(["Sl NO", "Company", "Warehouse", "Item Code", "Batch No",
		            "Negative Qty", "Value Difference (Company Currency)"])
		for i, r in enumerate(rows, 1):
			w.writerow([
				i,
				wh_to_co.get(r["warehouse"], ""),
				r["warehouse"],
				r["item_code"],
				r["batch_no"],
				f"{float(r['balance']):.2f}",
				f"{float(r['value_diff'] or 0):.2f}",
			])

	total_value = sum(float(r.get("value_diff") or 0) for r in rows)
	print(
		f"[audit_negative_batches_export_csv] "
		f"negative_buckets={len(rows)} total_qty={sum(float(r['balance']) for r in rows):.2f} "
		f"total_value={total_value:,.2f} (mixed company currencies) "
		f"csv={path}"
	)
