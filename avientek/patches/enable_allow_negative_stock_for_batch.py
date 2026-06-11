"""Ensure Stock Settings.allow_negative_stock_for_batch=1 on every migrate.

Sridhar/Venkatesh 2026-06-11: DN-LLC-26-00611-1 (Avientek Electronics
Trading L.L.C, item I028757 / Stores - AETL) hit ERPNext's "Negative
Stock Error" — Batch BN14575 reported negative "as of 04-06-2026
14:42:58" (the timestamp of an already-submitted DN-LLC-26-00627).

Tracing the true SLE chain via direct SQL proved BN14575 NEVER goes
negative — it ends at exactly +0 at 06-04. The error is a
false-positive from ERPNext's `get_batchwise_available_qty`
(stock/doctype/serial_and_batch_bundle/serial_and_batch_bundle.py:1546):
the walk over `get_available_qty_from_sabb` + `get_available_qty_from_stock_ledger`
processes ALL of history without a posting_datetime window, then
throws the moment running balance dips below 0 — regardless of
whether the chain recovers. After the 2026-06-03 cleanup nulled
SLE.batch_no on SBB-linked SLEs (correct on its own), this walk
became more prone to throwing false negatives.

Fix: enable Stock Settings.allow_negative_stock_for_batch=1. ERPNext's
per-batch check then short-circuits. Our before_submit hook
`avientek.stock.batch_negative_guard.check_batches_remain_positive`
(wired in hooks.py for DN/SI/SE/PR/PI) becomes the SOLE per-batch
validator — and it uses correct direct-SQL math that won't false-
positive on chains that end positive.

Idempotent. Runs on every migrate so any future Bench Update that
silently reverts the setting is re-corrected on the next deploy.
"""
import frappe


def execute():
    cur = frappe.db.get_single_value("Stock Settings", "allow_negative_stock_for_batch")
    if cur:
        print(f"[enable_allow_negative_stock_for_batch] already enabled (={cur}); no-op")
        return

    frappe.db.set_single_value("Stock Settings", "allow_negative_stock_for_batch", 1)
    frappe.db.commit()
    try:
        frappe.clear_cache(doctype="Stock Settings")
    except Exception:
        pass
    print(f"[enable_allow_negative_stock_for_batch] set 1 (was {cur!r}). "
          f"ERPNext per-batch check silenced. avientek.stock."
          f"batch_negative_guard is now the sole per-batch validator.")
