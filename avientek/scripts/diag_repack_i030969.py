"""Client-reported issue (Jithin, 2026-07-23, ticket MAT-STE-00774-7):
Repack Stock Entry for Item I030969 (source/consumed row, Stores - AETL)
shows the correct valuation rate while saved as a Draft, but the rate
persisted at Submit is ZERO. Doc snapshot at report time:

    MAT-STE-00774-7 (amended_from: MAT-STE-00774-6)
    purpose=Repack, posting_date=2026-07-23, posting_time=13:11:36,
    set_posting_time=1 (MANUALLY set, not "now")
    Row I030969: s_warehouse=Stores - AETL, qty=2, is_finished_item=0,
    set_basic_rate_manually=0 (rate is AUTO-fetched, not typed in)

ROOT-CAUSE HYPOTHESIS (code-level, from reading ERPNext v15 source):
Because set_basic_rate_manually=0 and s_warehouse is set, ERPNext calls
get_incoming_rate() -> BatchNoValuation for this row's batch. I030969
has_batch_no=1 and (per the site's Stock Settings) batch-wise valuation
is active, so if the specific batch picked here does NOT have
"Use Batch-wise Valuation" checked, valuation falls through to
DeprecatedBatchNoValuation.calculate_avg_rate_for_non_batchwise_valuation,
which explicitly sets:

    if not self.non_batchwise_balance_qty.get(batch_no):
        self.batch_avg_rate[batch_no] = 0.0

non_batchwise_balance_qty is built from prior Serial and Batch Entries
(and legacy SLEs) whose PARENT posting_datetime is strictly BEFORE this
Stock Entry's own posting_datetime (2026-07-23 13:11:36 — manually set).
If the batch's real inward receipt into Stores-AETL was posted at or
after that instant (e.g. entered later the same day, or backdated
differently), the query sees zero prior balance for the batch as of
13:11:36 -> rate computes as exactly 0. This is the same shape of bug
already confirmed for Item I024926 (diag_stock_valuation_i024926.py) —
a posting_datetime-ordering issue in batch valuation, not a random
race.

This script is READ-ONLY. It:
  1. Finds the current (latest, non-cancelled) amendment of this Stock
     Entry and dumps its I030969 row + any SLE/SBB already created for it.
  2. Identifies the batch(es) of I030969 with stock in the row's source
     warehouse, and each batch's use_batchwise_valuation flag.
  3. For each such batch, finds the most recent INWARD transaction and
     its posting_datetime, and compares it to the Stock Entry's own
     posting_datetime — this is the smoking gun check.
  4. If a Serial and Batch Bundle already exists on the row, re-runs
     ERPNext's own BatchNoValuation (read-only, no save) so we see its
     internal available_qty / batch_avg_rate state directly.

Run: bench --site <site> execute avientek.scripts.diag_repack_i030969.run
"""
import frappe

ITEM = "I030969"
STOCK_ENTRY_NAME_LIKE = "%STE-00774%"


def run():
    entries = frappe.db.sql(
        """SELECT name, purpose, docstatus, posting_date, posting_time, set_posting_time,
                  amended_from, creation
           FROM `tabStock Entry` WHERE name LIKE %s ORDER BY creation""",
        (STOCK_ENTRY_NAME_LIKE,), as_dict=True,
    )
    print(f"Stock Entries matching {STOCK_ENTRY_NAME_LIKE}: {len(entries)}")
    for e in entries:
        print(f"  {e}")

    if not entries:
        print("Nothing found — is this the right site/environment?")
        return

    current = entries[-1]
    print(f"\n=== Treating {current.name} as the live/current amendment ===")

    row = frappe.db.get_value(
        "Stock Entry Detail", {"parent": current.name, "item_code": ITEM},
        ["name", "s_warehouse", "t_warehouse", "qty", "basic_rate", "valuation_rate",
         "batch_no", "serial_and_batch_bundle", "set_basic_rate_manually",
         "allow_zero_valuation_rate"],
        as_dict=True,
    )
    print(f"Row for {ITEM}: {row}")
    if not row:
        print(f"{ITEM} not found on {current.name}")
        return

    warehouse = row.s_warehouse
    item_meta = frappe.db.get_value(
        "Item", ITEM, ["item_name", "has_batch_no", "has_serial_no", "valuation_method"],
        as_dict=True,
    )
    print(f"\nItem {ITEM} meta: {item_meta}")

    stock_settings = frappe.db.get_singles_dict("Stock Settings")
    print(f"Stock Settings.do_not_use_batchwise_valuation = "
          f"{stock_settings.get('do_not_use_batchwise_valuation')}")
    print(f"Stock Settings.auto_create_serial_and_batch_bundle_for_outward = "
          f"{stock_settings.get('auto_create_serial_and_batch_bundle_for_outward')}")

    # --- batches with stock for this item/warehouse, and their valuation flag
    print(f"\n-- Batches of {ITEM} in {warehouse!r} (current SBE-summed balance):")
    balances = frappe.db.sql(
        """
        SELECT sbe.batch_no,
               SUM(sbe.qty) AS balance,
               b.use_batchwise_valuation
        FROM `tabSerial and Batch Entry` sbe
        INNER JOIN `tabStock Ledger Entry` sle ON sle.serial_and_batch_bundle = sbe.parent
        LEFT JOIN `tabBatch` b ON b.name = sbe.batch_no
        WHERE sle.item_code=%s AND sle.warehouse=%s AND sle.is_cancelled=0
          AND sbe.batch_no IS NOT NULL AND sbe.batch_no != ''
        GROUP BY sbe.batch_no
        """,
        (ITEM, warehouse), as_dict=True,
    )
    for b in balances:
        print(f"  {b}")

    # --- the smoking-gun check: most recent INWARD posting per batch vs this SE's posting
    se_posting = f"{current.posting_date} {current.posting_time}"
    print(f"\nThis Stock Entry's posting_datetime = {se_posting} "
          f"(set_posting_time={current.set_posting_time})")

    for b in balances:
        inward = frappe.db.sql(
            """
            SELECT sle.voucher_type, sle.voucher_no, sle.posting_date, sle.posting_time,
                   sle.creation, sbe.qty, sbe.incoming_rate
            FROM `tabSerial and Batch Entry` sbe
            INNER JOIN `tabStock Ledger Entry` sle ON sle.serial_and_batch_bundle = sbe.parent
            WHERE sbe.batch_no=%s AND sle.item_code=%s AND sle.warehouse=%s
              AND sle.is_cancelled=0 AND sbe.qty > 0
            ORDER BY sle.posting_date DESC, sle.posting_time DESC
            LIMIT 5
            """,
            (b.batch_no, ITEM, warehouse), as_dict=True,
        )
        print(f"\n  Inward history for batch {b.batch_no} (use_batchwise_valuation="
              f"{b.use_batchwise_valuation}):")
        for i in inward:
            after_se = f"{i.posting_date} {i.posting_time}" >= se_posting
            flag = "  <== AT/AFTER this SE's posting_datetime! (would be excluded)" if after_se else ""
            print(f"    {i.voucher_type} {i.voucher_no}  posting={i.posting_date} {i.posting_time}  "
                  f"qty={i.qty}  incoming_rate={i.incoming_rate}{flag}")

    # --- if a bundle already exists on the row (submitted attempt), trace it directly
    if row.serial_and_batch_bundle:
        print(f"\n-- Bundle already attached: {row.serial_and_batch_bundle} — tracing BatchNoValuation")
        _trace_bundle(row.serial_and_batch_bundle)
    else:
        print(f"\nNo serial_and_batch_bundle on the row yet (doc is still Draft — "
              f"bundle is created fresh at submit-time validate).")


def _trace_bundle(bundle_name):
    from erpnext.stock.serial_batch_bundle import BatchNoValuation
    from erpnext.stock.utils import get_valuation_method

    bundle = frappe.get_doc("Serial and Batch Bundle", bundle_name)
    print(f"Bundle {bundle_name}: item={bundle.item_code} warehouse={bundle.warehouse} "
          f"type={bundle.type_of_transaction} posting={bundle.posting_date} {bundle.posting_time} "
          f"docstatus={bundle.docstatus}")

    for entry in bundle.entries:
        b = frappe.db.get_value(
            "Batch", entry.batch_no, ["use_batchwise_valuation"], as_dict=True
        ) if entry.batch_no else None
        print(f"  entry batch_no={entry.batch_no!r} qty={entry.qty} "
              f"incoming_rate={entry.incoming_rate} batch_meta={b}")

    print(f"\nvaluation_method({bundle.item_code}) = {get_valuation_method(bundle.item_code)}")

    sle = bundle.get_sle_for_outward_transaction()
    sn_obj = BatchNoValuation(sle=sle, item_code=bundle.item_code, warehouse=bundle.warehouse)
    print(f"batchwise_valuation_batches     = {sn_obj.batchwise_valuation_batches}")
    print(f"non_batchwise_valuation_batches  = {sn_obj.non_batchwise_valuation_batches}")
    print(f"available_qty                   = {dict(sn_obj.available_qty)}")
    print(f"batch_avg_rate                  = {dict(getattr(sn_obj, 'batch_avg_rate', {}))}")
    print(f"non_batchwise_balance_qty       = {dict(getattr(sn_obj, 'non_batchwise_balance_qty', {}))}")
    print(f"non_batchwise_balance_value     = {dict(getattr(sn_obj, 'non_batchwise_balance_value', {}))}")
