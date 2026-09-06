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


# ──────────────────────────────────────────────────────────────────────────
# Negative stock VALUE detector (TSK-2026-00702, Option 1).
# Companion to the negative-QUANTITY detector above. Batch-wise valuation on
# mixed-rate batches can book negative COGS on individual deliveries (value
# concentrates in leftover units). Over an item's life this is net-zero
# (a presentation artifact, not a loss), but Accounts wants visibility. This
# is READ-ONLY monitoring only — it never changes any valuation.
# ──────────────────────────────────────────────────────────────────────────

# ignore sub-currency-unit dust; only surface material negatives
VALUE_TOLERANCE = 1.0


def find_negative_stock_values(days=45, threshold=VALUE_TOLERANCE):
    """Read-only. Return two lists:
      live_bins  – Bins currently holding negative stock VALUE (or a negative
                   valuation_rate on positive qty) beyond `threshold` — the
                   actionable, live exposures.
      recent_sles – Stock Ledger Entries in the last `days` whose running
                   balance value went negative (the delivery-level artifact the
                   Stock Ledger report shows), each tagged with the item's
                   CURRENT bin qty so cosmetic/sold-out (qty 0) can be told
                   apart from live cases.
    """
    from frappe.utils import add_days, today

    live_bins = frappe.db.sql(
        """
        SELECT item_code, warehouse, actual_qty, stock_value, valuation_rate
        FROM `tabBin`
        WHERE stock_value < %(neg)s
           OR (actual_qty > 0.001 AND valuation_rate < 0 AND stock_value < %(neg)s)
        ORDER BY stock_value ASC
        """,
        {"neg": -flt(threshold)}, as_dict=True,
    )

    recent_sles = frappe.db.sql(
        """
        SELECT sle.item_code, sle.warehouse, sle.voucher_type, sle.voucher_no,
               sle.posting_date, sle.valuation_rate, sle.stock_value,
               COALESCE(b.actual_qty, 0) AS current_bin_qty
        FROM `tabStock Ledger Entry` sle
        LEFT JOIN `tabBin` b ON b.item_code = sle.item_code AND b.warehouse = sle.warehouse
        WHERE sle.is_cancelled = 0
          AND sle.posting_date >= %(since)s
          AND sle.stock_value < %(neg)s
        ORDER BY sle.stock_value ASC
        """,
        {"since": add_days(today(), -int(days)), "neg": -flt(threshold)}, as_dict=True,
    )
    return {"live_bins": live_bins, "recent_sles": recent_sles}


@frappe.whitelist()
def get_negative_stock_values(days=45):
    """Whitelisted, READ-ONLY getter for on-demand review."""
    frappe.only_for(("System Manager", "Stock Manager", "Stock User", "Accounts Manager"))
    res = find_negative_stock_values(days=int(days))
    return {
        "live_bin_count": len(res["live_bins"]),
        "recent_sle_count": len(res["recent_sles"]),
        **res,
    }


def scan_and_log_negative_stock_values():
    """Scheduled DETECTOR (daily). Read-only. One Error Log summary when a
    material negative stock VALUE is present (live Bin) or was booked recently
    (delivery-level). Idempotent (no-op when clean). Never writes valuation."""
    res = find_negative_stock_values()
    live, recent = res["live_bins"], res["recent_sles"]
    if not live and not recent:
        return 0

    parts = []
    if live:
        parts.append("LIVE negative-value stock (actionable):")
        parts += [
            f"  {r.item_code} @ {r.warehouse}: value={flt(r.stock_value, 2)} "
            f"qty={flt(r.actual_qty, 3)} rate={flt(r.valuation_rate, 2)}"
            for r in live[:100]
        ]
    if recent:
        parts.append("\nRecent deliveries that booked negative balance value "
                     "(last 45d; current_bin_qty 0 = sold-out/cosmetic, net-zero):")
        parts += [
            f"  {r.posting_date} {r.item_code} @ {r.warehouse} "
            f"{r.voucher_type} {r.voucher_no}: bal_value={flt(r.stock_value, 2)} "
            f"rate={flt(r.valuation_rate, 2)} current_bin_qty={flt(r.current_bin_qty, 3)}"
            for r in recent[:100]
        ]

    frappe.log_error(
        title="Negative Stock Value Detected",
        message=("Batch-valuation drift booked negative stock value. Net impact "
                 "over an item's life is usually zero (cosmetic), but review live "
                 "(qty>0) cases.\n\n" + "\n".join(parts)),
    )
    return len(live) + len(recent)
