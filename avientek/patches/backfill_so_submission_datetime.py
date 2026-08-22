# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# One-time backfill of Sales Order.custom_submission_datetime for HISTORICAL
# orders (submitted before the on-submit stamp hook went live 2026-08-03), so
# the Avientek Stock Allocation report (CR-01) shows and allocates by the real
# submission time instead of falling back to the order booking date. #0512.
#
# Delivered as a PATCH (not a manual `bench execute`) because Frappe Cloud
# gives no shell and its System Console is sandboxed for writes — a patch runs
# automatically during the deploy's `bench migrate`.
#
# Recovers the timestamp from Frappe's Version log (the record of the
# docstatus 0 -> 1 change). Orders with no such record (e.g. imported
# already-submitted, ~16% of open orders) are left blank and keep the
# booking-date fallback — there is no submit time to recover for them.
# Report-only field (no_copy), update_modified=False. Idempotent: only rows
# with a NULL custom_submission_datetime are touched, so a re-run is a no-op.
#
# Approved by Rahul (CR-01 owner) via Sammish 2026-08-22, extending CR-01's
# original "historical orders keep booking-date logic" scope.

from avientek.scripts.backfill_so_submission_datetime import run


def execute():
    run(commit=True)
