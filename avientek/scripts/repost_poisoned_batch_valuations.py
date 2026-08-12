# One-time correction run for the batch-valuation blow-up (tickets #0492/#0493).
#
# PRECONDITION: the posting_datetime fix (PR #27 — backfill patch +
# ensure_posting_datetime hook) MUST already be deployed/migrated, so the
# batch records are visible to valuation. Reposting BEFORE that fix would
# just re-compute the same wrong numbers.
#
# What it does: finds every item + warehouse whose stock ledger shows the
# corruption signature (a single transaction that moved > 1,000,000 in value,
# or a current negative balance while qty is positive), then runs ERPNext's
# Repost Item Valuation for each, from the earliest bad date, and records the
# stock value before and after.
#
# SAFE BY DEFAULT: dry_run=1 only prints the plan and changes nothing. Run it
# that way first, review, then run with dry_run=0 AFTER Accounts opens the
# frozen months. Items in a still-frozen period will fail cleanly and be
# listed at the end (no partial damage) so they can be retried once opened.
#
# Usage (from bench):
#   bench --site <site> execute avientek.scripts.repost_poisoned_batch_valuations.run
#   bench --site <site> execute avientek.scripts.repost_poisoned_batch_valuations.run --kwargs "{'dry_run':0}"
#   bench --site <site> execute avientek.scripts.repost_poisoned_batch_valuations.run --kwargs "{'dry_run':0,'limit':10}"

import frappe
from frappe.utils import add_days, getdate

# HARD FLOOR — Accounts (Jithin) approved correcting 2026 only. 2025 is
# audited and closed; this run must NEVER post into 2025. Any pair whose
# problem starts before this date is skipped here and handled separately
# (a current-dated Stock Reconciliation, with Accounts sign-off).
FLOOR_DATE = "2026-01-01"


def _affected_pairs():
    """item + warehouse pairs showing the corruption signature, with the
    earliest date to correct from. ONLY pairs whose first bad entry is in
    2026 (>= FLOOR_DATE) are returned — 2025-rooted pairs are excluded so
    we never touch the closed year."""
    return frappe.db.sql(
        """
        SELECT * FROM (
            SELECT sle.item_code, sle.warehouse,
                   DATE(MIN(CASE
                        WHEN ABS(sle.stock_value_difference) > 1000000
                          OR (sle.stock_value < 0 AND sle.qty_after_transaction > 0)
                        THEN sle.posting_date END)) AS bad_from
            FROM `tabStock Ledger Entry` sle
            WHERE sle.is_cancelled = 0
            GROUP BY sle.item_code, sle.warehouse
            HAVING MAX(ABS(sle.stock_value_difference) > 1000000) = 1
                OR MAX(sle.stock_value < 0 AND sle.qty_after_transaction > 0) = 1
        ) t
        WHERE t.bad_from >= %(floor)s
        ORDER BY t.bad_from
        """,
        {"floor": FLOOR_DATE},
        as_dict=True,
    )


def _current_stock_value(item_code, warehouse):
    row = frappe.db.get_value(
        "Stock Ledger Entry",
        {"item_code": item_code, "warehouse": warehouse, "is_cancelled": 0},
        ["stock_value", "qty_after_transaction"],
        order_by="posting_datetime desc, creation desc",
        as_dict=True,
    )
    return row or frappe._dict({"stock_value": None, "qty_after_transaction": None})


def run(dry_run=1, limit=0):
    from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost

    dry_run = int(dry_run)
    limit = int(limit)

    pairs = _affected_pairs()
    if limit:
        pairs = pairs[:limit]

    print(f"\n=== Batch valuation correction ===")
    print(f"mode: {'DRY RUN (no changes)' if dry_run else 'LIVE REPOST'}")
    print(f"affected item+warehouse pairs: {len(pairs)}\n")

    done, failed = [], []
    for i, p in enumerate(pairs, 1):
        before = _current_stock_value(p.item_code, p.warehouse)
        # start one day before the first bad entry, so the recompute has a clean
        # base — but NEVER before the floor (2025 is closed).
        from_date = add_days(getdate(p.bad_from), -1) if p.bad_from else None
        if from_date and getdate(from_date) < getdate(FLOOR_DATE):
            from_date = getdate(FLOOR_DATE)
        # absolute safety: refuse to repost into the closed year
        if not from_date or getdate(from_date) < getdate(FLOOR_DATE):
            print(f"[{i}/{len(pairs)}] {p.item_code} @ {p.warehouse}  ->  SKIPPED "
                  f"(would touch pre-{FLOOR_DATE}; handle via Stock Reconciliation)")
            failed.append((p.item_code, p.warehouse, f"pre-{FLOOR_DATE} — skipped"))
            continue
        line = (f"[{i}/{len(pairs)}] {p.item_code} @ {p.warehouse} "
                f"| from {from_date} | before value = {before.stock_value}")

        if dry_run:
            print(line + "  (dry run — skipped)")
            continue

        try:
            riv = frappe.get_doc({
                "doctype": "Repost Item Valuation",
                "based_on": "Item and Warehouse",
                "item_code": p.item_code,
                "warehouse": p.warehouse,
                "posting_date": from_date,
                "posting_time": "00:00:00",
                "allow_negative_stock": 1,
            })
            riv.flags.ignore_permissions = True
            riv.insert()
            riv.submit()
            repost(riv)
            frappe.db.commit()
            after = _current_stock_value(p.item_code, p.warehouse)
            print(line + f"  ->  after value = {after.stock_value}")
            done.append((p.item_code, p.warehouse, before.stock_value, after.stock_value))
        except Exception as e:
            frappe.db.rollback()
            msg = str(e).splitlines()[0][:150]
            print(line + f"  ->  FAILED: {msg}")
            failed.append((p.item_code, p.warehouse, msg))

    print(f"\n=== Summary ===")
    print(f"reposted OK: {len(done)}")
    print(f"failed (e.g. still-frozen period — retry after opening): {len(failed)}")
    for it, wh, msg in failed:
        print(f"  - {it} @ {wh}: {msg}")
    return {"total": len(pairs), "done": len(done), "failed": len(failed)}
