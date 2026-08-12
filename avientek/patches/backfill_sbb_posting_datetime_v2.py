# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Re-run of backfill_sbb_posting_datetime. The first version derived the
# missing posting_datetime only from the linked Stock Ledger Entry or the
# bundle's own posting_date. On prod that left ~766 bundles NULL (mostly 2025
# Purchase Receipts whose SLE also had no posting_datetime and whose bundle
# had no posting_date) — still invisible to batch valuation.
#
# This version calls the shared backfill which now also falls back to the
# linked VOUCHER's posting_date + posting_time, so every bundle with a valid
# stock voucher gets stamped. Idempotent (only NULL rows are touched).

from avientek.events.serial_batch_bundle import backfill_missing_posting_datetime


def execute():
    fixed = backfill_missing_posting_datetime()
    print(f"[backfill_sbb_posting_datetime_v2] stamped {fixed} remaining bundle(s)")
