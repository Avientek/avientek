"""Backfill Quotation.custom_total_margin_percent_new to the correct value
(margin / selling × 100) across every quotation.

Pre-fix (before commit ba5de36), the margin percent was being stored as
the *sum* of each Brand Summary row's `margin_percent` — which is
mathematically wrong. For QN-LLC-26-00316 it showed 151.05% instead of
the correct 17.92%.

The new calc runs on every save, so any quotation that gets re-saved
fixes itself. But tens of thousands of existing quotations still carry
the wrong value. Finance flagged this on "many quotes". This patch
walks every quotation once and writes the correct value via
frappe.db.set_value (bypasses allow_on_submit and doesn't bump
`modified`, so submitted docs get fixed quietly without showing up as
"edited today").

Idempotent — skips rows already within 0.01% of the correct value.
"""

import frappe
from frappe.utils import flt


BATCH = 500


def execute():
    rows = frappe.db.sql(
        """
        SELECT name,
               custom_total_selling_new   AS selling,
               custom_total_margin_new    AS margin,
               custom_total_margin_percent_new AS pct_stored
        FROM `tabQuotation`
        WHERE IFNULL(custom_total_selling_new, 0) > 0
        """,
        as_dict=True,
    )
    print(f"[backfill_quotation_total_margin_percent] scanned: {len(rows)}")

    updated = 0
    for i, r in enumerate(rows, 1):
        selling = flt(r.selling)
        margin = flt(r.margin)
        if selling <= 0:
            continue
        correct_pct = flt(margin / selling * 100, 4)
        if abs(flt(r.pct_stored) - correct_pct) < 0.01:
            continue
        frappe.db.set_value(
            "Quotation", r.name,
            "custom_total_margin_percent_new", correct_pct,
            update_modified=False,
        )
        updated += 1
        if updated % BATCH == 0:
            frappe.db.commit()
            print(f"  committed {updated} so far")

    frappe.db.commit()
    print(f"[backfill_quotation_total_margin_percent] updated: {updated}")
