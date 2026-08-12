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


def backfill_missing_posting_datetime():
    """Scheduled backstop (hourly). The before_save/before_submit hook above
    covers the normal save/submit paths, but we cannot prove every exotic /
    programmatic creation path (intercompany auto-docs, repost, direct API)
    fires it. This catches ANY submitted, non-cancelled bundle that still has
    a NULL posting_datetime — from any path — and stamps it from the linked
    SLE (authoritative) or its own posting_date. Idempotent; a no-op when
    there is nothing to fix, so it is safe to run every hour.

    This is the 'no recurrence' guarantee that does not depend on knowing
    which path created the NULL."""
    rows = frappe.db.sql(
        """
        SELECT sbb.name, sbb.posting_date, sbb.posting_time, sle.posting_datetime AS sle_dt
        FROM `tabSerial and Batch Bundle` sbb
        LEFT JOIN `tabStock Ledger Entry` sle
               ON sle.serial_and_batch_bundle = sbb.name AND sle.is_cancelled = 0
        WHERE sbb.posting_datetime IS NULL
          AND sbb.docstatus = 1 AND sbb.is_cancelled = 0
        """,
        as_dict=True,
    )
    fixed = 0
    for r in rows:
        dt = r.sle_dt or (f"{r.posting_date} {r.posting_time or '00:00:00'}" if r.posting_date else None)
        if not dt:
            continue
        frappe.db.set_value(
            "Serial and Batch Bundle", r.name,
            {"posting_datetime": dt, "posting_date": get_datetime(dt).date()},
            update_modified=False,
        )
        fixed += 1
    if fixed:
        frappe.db.commit()
        frappe.log_error(
            title="SBB posting_datetime backstop",
            message=f"Backstop stamped posting_datetime on {fixed} bundle(s) that "
                    f"were created without it. Investigate the creation path.",
        )
    return fixed


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
