"""Patch A5 — SYSTEMIC FIX for ERPNext v15 SBB double-count bug.

Sridhar 2026-06-03 — final dynamic defense.

Root cause recap: ERPNext v15 stores batch info in TWO places when an
SLE has a Serial and Batch Bundle attached:
  - tabSerial and Batch Entry.qty  (the SBB child row — modern v15)
  - tabStock Ledger Entry.batch_no (the legacy direct column)

Many ERPNext functions sum both sources without de-duplicating, so the
same transaction gets counted twice. We monkey-patched 3 such functions
(get_stock_ledgers_batches, batch_wise_balance_history, and
DeprecatedBatchNoValuation.get_sle_for_batches), but there may be other
code paths we haven't found yet — and ERPNext keeps adding new ones.

This patch eliminates the BUG AT THE DATA LAYER instead of patching every
reader. For every SLE with a non-empty serial_and_batch_bundle, set
batch_no = NULL. The SBB child rows still carry the batch info, so
legitimate SBB-aware code paths still work. Legacy code paths that read
SLE.batch_no simply see NULL on these rows and naturally skip them — no
more double-count anywhere in the system.

Pre-v15 / direct-batch SLEs (no SBB attached) keep their batch_no — the
legacy code paths still need to see those.

Combined with `enforce_sbb_null_batch_no` doc_events hook (on Stock
Ledger Entry.before_save), this gives us:
  - Existing data: cleaned by this patch (one-time SQL update)
  - Future data: enforced by the hook (every new/edited SLE)

Idempotent. Safe to re-run.
"""
import frappe


def execute():
	# Count rows that violate the invariant before fix
	before = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabStock Ledger Entry`
		WHERE serial_and_batch_bundle IS NOT NULL
		  AND serial_and_batch_bundle != ''
		  AND batch_no IS NOT NULL
		  AND batch_no != ''
	""")[0][0]
	print(f"[null_batch_no_on_all_sbb_sles] SBB-linked SLEs with non-null batch_no: {before}")

	if before == 0:
		print(f"[null_batch_no_on_all_sbb_sles] data layer already clean — no-op")
		return

	# Bulk NULL the batch_no on SBB-linked SLEs.
	# The SBE child rows still carry the batch info, so no data loss.
	frappe.db.sql("""
		UPDATE `tabStock Ledger Entry`
		SET batch_no = NULL
		WHERE serial_and_batch_bundle IS NOT NULL
		  AND serial_and_batch_bundle != ''
		  AND batch_no IS NOT NULL
		  AND batch_no != ''
	""")
	frappe.db.commit()

	# Verify
	after = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabStock Ledger Entry`
		WHERE serial_and_batch_bundle IS NOT NULL
		  AND serial_and_batch_bundle != ''
		  AND batch_no IS NOT NULL
		  AND batch_no != ''
	""")[0][0]
	print(f"[null_batch_no_on_all_sbb_sles] cleaned: {before - after} rows. "
	      f"Residual violations: {after}")
