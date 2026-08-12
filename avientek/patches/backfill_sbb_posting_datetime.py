# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Backfill posting_datetime on every Serial and Batch Bundle where it is
# NULL. See avientek/events/serial_batch_bundle.py for the full root-cause
# writeup (helpdesk #0492 / #0493): NULL posting_datetime makes a bundle
# invisible to ERPNext's batch valuation, which is what let the July 2026
# batch rates explode to billions.
#
# This patch only corrects the TIMESTAMP metadata on the bundles; it does
# NOT repost stock ledgers or touch the GL. Already-poisoned SLE/GL values
# must be corrected separately via Repost Item Valuation (Accounts-gated,
# frozen-period aware). Making the bundles visible first is a precondition
# for that repost to recompute correct rates.
#
# Idempotent: only rows with NULL posting_datetime are touched.

import frappe
from frappe.utils import getdate


def execute():
    rows = frappe.db.sql(
        """
        SELECT sbb.name, sbb.posting_date, sbb.posting_time,
               sle.posting_datetime AS sle_dt
        FROM `tabSerial and Batch Bundle` sbb
        LEFT JOIN `tabStock Ledger Entry` sle
               ON sle.serial_and_batch_bundle = sbb.name AND sle.is_cancelled = 0
        WHERE sbb.posting_datetime IS NULL
          AND sbb.docstatus = 1 AND sbb.is_cancelled = 0
        """,
        as_dict=True,
    )

    fixed = 0
    unresolved = []
    for r in rows:
        dt = None
        # 1. authoritative: the linked SLE's posting_datetime
        if r.sle_dt:
            dt = r.sle_dt
        # 2. the bundle's own posting_date (+ time)
        elif r.posting_date:
            dt = f"{r.posting_date} {r.posting_time or '00:00:00'}"

        if not dt:
            unresolved.append(r.name)
            continue

        # db.set_value on the child-of-nothing top-level doc; bypass modified
        frappe.db.set_value(
            "Serial and Batch Bundle", r.name,
            {"posting_datetime": dt,
             "posting_date": getdate(dt)},
            update_modified=False,
        )
        fixed += 1

    frappe.db.commit()
    print(f"[backfill_sbb_posting_datetime] set posting_datetime on {fixed} bundle(s)"
          + (f"; {len(unresolved)} unresolved: {unresolved[:20]}" if unresolved else ""))
