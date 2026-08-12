# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Guard: every Serial and Batch Bundle MUST carry a posting_datetime.
#
# Why this matters (root cause of the July 2026 stock-value blow-up,
# helpdesk #0492 / #0493): ERPNext's batch valuation
# (BatchNoValuation.get_batch_no_ledgers) sums a batch's prior qty/value
# with the filter `parent.posting_datetime < sle.posting_datetime`. A
# Serial and Batch Bundle whose posting_datetime is NULL is SILENTLY
# EXCLUDED from that sum (NULL < x is not true). When inward (GRN) bundles
# are excluded, a batch's available_qty computes as ~0, so an outward
# delivery divides the residual value by ~0 and books an astronomical rate
# (e.g. DN-LLC-26-00856 booked 6.5 billion AED for 1 unit). Because the
# valuation is self-referential, that poisoned value then amplifies on
# every later outward of the same batch+warehouse.
#
# Stock ERPNext only sets posting_datetime when the parent voucher passes
# BOTH posting_date and posting_time (serial_and_batch_bundle.py
# set_serial_and_batch_values ~line 828). Some creation paths don't, so
# the field lands NULL. This hook closes that gap for every bundle.

import frappe
from frappe.utils import get_datetime


def ensure_posting_datetime(doc, method=None):
    """Backfill posting_datetime on a bundle if it is missing, so batch
    valuation never excludes it. Order of truth:
      1. the bundle's linked Stock Ledger Entry (authoritative — this is the
         exact value batch valuation compares against),
      2. the bundle's own posting_date + posting_time,
      3. the linked voucher's posting_date + posting_time.
    Never overwrites an existing posting_datetime."""
    if doc.get("posting_datetime"):
        return

    dt = _from_sle(doc) or _from_own_fields(doc) or _from_voucher(doc)
    if dt:
        doc.posting_datetime = dt
        if not doc.get("posting_date"):
            doc.posting_date = get_datetime(dt).date()


def _from_sle(doc):
    if not doc.get("name"):
        return None
    return frappe.db.get_value(
        "Stock Ledger Entry",
        {"serial_and_batch_bundle": doc.name, "is_cancelled": 0},
        "posting_datetime",
    )


def _from_own_fields(doc):
    if doc.get("posting_date"):
        return get_datetime(f"{doc.posting_date} {doc.get('posting_time') or '00:00:00'}")
    return None


def _from_voucher(doc):
    if not (doc.get("voucher_type") and doc.get("voucher_no")):
        return None
    if not frappe.db.exists(doc.voucher_type, doc.voucher_no):
        return None
    vals = frappe.db.get_value(
        doc.voucher_type, doc.voucher_no, ["posting_date", "posting_time"], as_dict=True
    )
    if vals and vals.get("posting_date"):
        return get_datetime(f"{vals.posting_date} {vals.get('posting_time') or '00:00:00'}")
    return None
