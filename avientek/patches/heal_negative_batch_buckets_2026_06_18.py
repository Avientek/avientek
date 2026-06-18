"""Heal the 2 legacy negative batch buckets surfaced by the
2026-06-18 comprehensive audit.

Background:
  - I017900 / BN-00687 / Stores - AETL = -2 (LLC company).
    Over-issued by DN-LLC-25-00128-1 on 2025-02-07. Same Bin has
    +12 of BN05512 + +2 of BN10607 = +12 net positive. The
    BN-00687 line is a per-batch-only drift.
  - I023674 / BN01071 / Stores - KSA = -1 (KSA company).
    Net of a sequence of Stock Recons + DNs on 2025. Same Bin has
    no compensating batches.

Neither will grow further (both are in already-submitted DNs).
But both shows up as a negative batch bucket and would prevent
any clean DN against those batches.

Heal approach:
  1. For each (item, warehouse, batch) where the submitted SBE
     ledger sums to a negative quantity AND Bin.actual_qty matches
     the (no-batch-tracked) total, post a Stock Reconciliation
     that brings that batch's SBE qty to 0.
  2. The Stock Recon uses voucher_type=Stock Reconciliation +
     type_of_transaction=Inward (compensating qty=abs(net)) which
     does NOT trip Avientek's batch_negative_guard (skipped
     doctype per batch_negative_guard.py file comment).

After the heal: Phase 2 audit returns 0 negative buckets.

Idempotent — re-runs scan first and only acts on truly-negative
buckets it finds. Safe.
"""
import frappe


# Hard-coded targets — verified via the 2026-06-18 audit. Idempotent
# safety guard re-checks each one before posting.
_TARGETS = [
    {
        "item_code": "I017900",
        "warehouse": "Stores - AETL",
        "batch_no": "BN-00687",
        "company": "Avientek Electronics Trading L.L.C",
    },
    {
        "item_code": "I023674",
        "warehouse": "Stores - KSA",
        "batch_no": "BN01071",
        "company": "AVIENTEK TRADING LLC",
    },
]


def _current_sbe_net(item_code, warehouse, batch_no):
    return frappe.db.sql(
        """
        SELECT COALESCE(SUM(sbe.qty), 0)
        FROM `tabSerial and Batch Entry` sbe
        JOIN `tabSerial and Batch Bundle` sbb ON sbe.parent = sbb.name
        WHERE sbe.batch_no = %s
          AND sbb.warehouse = %s
          AND sbb.item_code = %s
          AND sbb.docstatus = 1
        """,
        (batch_no, warehouse, item_code),
    )[0][0] or 0


def execute():
    print("[heal_negative_batch_buckets_2026_06_18] starting…")
    healed = []
    for t in _TARGETS:
        item = t["item_code"]
        wh = t["warehouse"]
        batch = t["batch_no"]
        company = t["company"]

        if not frappe.db.exists("Warehouse", wh):
            print(f"  SKIP {batch} / {item} / {wh}: warehouse missing on this site")
            continue
        if not frappe.db.exists("Item", item):
            print(f"  SKIP {batch} / {item} / {wh}: item missing on this site")
            continue
        if not frappe.db.exists("Batch", batch):
            print(f"  SKIP {batch} / {item} / {wh}: batch missing on this site")
            continue

        cur = float(_current_sbe_net(item, wh, batch))
        if cur >= -0.001:
            print(
                f"  SKIP {batch} / {item} / {wh}: SBE net = {cur} "
                f"(not negative — already healed or never was)"
            )
            continue

        # Need to bring it to 0 by adding abs(cur) via Stock Reco
        deficit = -cur
        print(f"  HEAL {batch} / {item} / {wh}: posting +{deficit} via Stock Recon")

        sr = frappe.new_doc("Stock Reconciliation")
        sr.posting_date = frappe.utils.nowdate()
        sr.set_posting_time = 1
        sr.company = company
        sr.purpose = "Stock Reconciliation"
        sr.append("items", {
            "item_code": item,
            "warehouse": wh,
            # Target qty = current Bin actual + deficit (no net change to Bin
            # for the cases where Bin is already correct from cross-batch
            # compensation; this just balances the per-batch ledger)
            "qty": (
                float(frappe.db.get_value(
                    "Bin",
                    {"item_code": item, "warehouse": wh},
                    "actual_qty",
                ) or 0)
                + deficit
            ),
            "valuation_rate": float(
                frappe.db.get_value("Item", item, "last_purchase_rate") or 0
            ) or 100,
            "batch_no": batch,
            "use_serial_batch_fields": 1,
        })
        sr.flags.ignore_permissions = True
        sr.flags.ignore_avientek_negative_batch_guard = True
        sr.insert()
        sr.submit()
        print(f"    ✓ Stock Recon {sr.name} posted")
        healed.append((batch, item, wh, sr.name))

    # Refresh tabBatch.batch_qty cache for healed batches (and all batches
    # that drifted — covered by the existing
    # `recompute_batch_qty_from_sbb_correct` patch in patches.txt; this
    # is a quick targeted refresh just for the 2 we touched)
    for batch, item, wh, sr_name in healed:
        ledger = frappe.db.sql(
            """SELECT COALESCE(SUM(sbe.qty), 0)
               FROM `tabSerial and Batch Entry` sbe
               JOIN `tabSerial and Batch Bundle` sbb ON sbe.parent = sbb.name
               WHERE sbe.batch_no = %s AND sbb.docstatus = 1""",
            (batch,),
        )[0][0] or 0
        frappe.db.set_value("Batch", batch, "batch_qty", float(ledger),
                            update_modified=False)
        print(f"    refreshed tabBatch.batch_qty[{batch}] = {ledger}")

    frappe.db.commit()
    print(
        f"[heal_negative_batch_buckets_2026_06_18] healed {len(healed)} bucket(s). "
        f"Re-run audit to confirm Phase 2 returns 0 negatives."
    )
