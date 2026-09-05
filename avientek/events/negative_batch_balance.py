"""Negative batch-balance detection (TSK-2026-00698).

Why: ERPNext core `update_batch_qty` validates a delivery against a batch's
GLOBAL `batch_qty` (the sum across ALL warehouses), so a NEGATIVE balance of a
batch in one warehouse silently blocks a legitimate delivery of the SAME batch
from another warehouse (#0529: BN19252 was +16 @ Stores-AETL but -1 @
T1-7SEAS-A → global 15 → the 16-unit AETL delivery threw "negative batch
quantity"). "Recalculate Batch Qty" does NOT help — the negative is real.

This module DETECTS those negatives (read-only) so they can be cleared with a
Stock Reconciliation before they block anything. It never writes stock — the
correction is a human-reviewed Stock Reconciliation
(`avientek.scripts.draft_negative_batch_reconciliations`).

The balance is computed with the SAME aggregation ERPNext itself uses in
`get_available_batches` (serial_and_batch_bundle.py): SUM(`Serial and Batch
Entry`.qty) over non-cancelled Stock Ledger Entries, grouped by
(batch_no, warehouse), for non-disabled batches. `for_stock_levels` semantics:
expired batches are INCLUDED (a negative is a negative regardless of expiry).
"""

import frappe
from frappe.utils import flt

# quantities are effectively whole numbers here; ignore sub-milli float dust
NEGATIVE_TOLERANCE = -0.001


def find_negative_batch_balances(company=None):
    """Return a list of {batch_no, warehouse, company, qty} for every batch
    whose actual per-warehouse balance is negative. Read-only.

    Mirrors erpnext ...serial_and_batch_bundle.get_available_batches so the
    result matches what ERPNext considers the batch's real balance.
    """
    conditions = ""
    params = {}
    if company:
        conditions = " AND sle.company = %(company)s"
        params["company"] = company

    return frappe.db.sql(
        f"""
        SELECT sbe.batch_no, sbe.warehouse, sle.company, SUM(sbe.qty) AS qty
        FROM `tabStock Ledger Entry` sle
        INNER JOIN `tabSerial and Batch Entry` sbe
                ON sle.serial_and_batch_bundle = sbe.parent
        INNER JOIN `tabBatch` batch
                ON sbe.batch_no = batch.name
        WHERE batch.disabled = 0
          AND sle.is_cancelled = 0
          {conditions}
        GROUP BY sbe.batch_no, sbe.warehouse, sle.company
        HAVING SUM(sbe.qty) < {NEGATIVE_TOLERANCE}
        ORDER BY SUM(sbe.qty) ASC
        """,
        params,
        as_dict=True,
    )


@frappe.whitelist()
def get_negative_batch_balances(company=None):
    """Whitelisted, READ-ONLY getter — safe to call (e.g. on prod) to size and
    verify the negative-batch backlog before/after a correction sweep."""
    frappe.only_for(("System Manager", "Stock Manager", "Stock User", "Accounts Manager"))
    rows = find_negative_batch_balances(company)
    return {
        "count": len(rows),
        "rows": rows,
    }


def scan_and_log_negative_batch_balances():
    """Scheduled DETECTOR (daily). Read-only. Writes ONE Error Log summary when
    negative batch balances exist so Stock/Accounts catch them before they
    block a delivery. Never writes stock. Idempotent (no-op when clean)."""
    rows = find_negative_batch_balances()
    if not rows:
        return 0

    shown = rows[:200]
    lines = [
        f"{r.batch_no} @ {r.warehouse} ({r.company}): {flt(r.qty, 3)}" for r in shown
    ]
    for_more = ""
    if len(rows) > len(shown):
        for_more = f"\n… and {len(rows) - len(shown)} more"

    frappe.log_error(
        title="Negative Batch Balances Detected",
        message=(
            f"{len(rows)} batch+warehouse balance(s) are NEGATIVE.\n\n"
            "These block deliveries of the SAME batch from other warehouses "
            "(ERPNext validates the batch's global total across all warehouses).\n"
            "Correct each with a Stock Reconciliation to qty 0, or run "
            "avientek.scripts.draft_negative_batch_reconciliations.\n\n"
            + "\n".join(lines)
            + for_more
        ),
    )
    return len(rows)
