"""Client-reported issue: Item I024926 (C6R Ceiling Speakers Black),
Warehouse "Stores - KSA", Company "AVIENTEK TRADING LLC" shows an
absurd Valuation Rate (5,805.90/pc) on the Stock Balance report.

From the downloaded Stock Ledger, the Delivery Note DN-AT-26-00397
(2026-06-30 19:20, 48 pcs out) was valued at an Outgoing Rate of
10.1 instead of the ~241.93 average cost that was on the books two
minutes earlier (Purchase Receipt GRN-KSA-26-00129, 19:18). That
undercharges the 48 units leaving and dumps almost all their true
cost (11,611.80) onto the 2 units left in stock.

This script pulls the raw facts needed to confirm *why*: item's
batch/serial tracking + valuation method, Stock Settings'
do_not_use_batchwise_valuation flag, the three raw SLEs, and the
Serial and Batch Bundle + child rows behind each voucher — so we
diagnose from data, not guesswork.

Run: bench --site avientek.localhost execute avientek.scripts.diag_stock_valuation_i024926.run
"""
import frappe

ITEM = "I024926"
WAREHOUSE = "Stores - KSA"


def run():
    item = frappe.db.get_value(
        "Item", ITEM,
        ["item_name", "has_batch_no", "has_serial_no", "valuation_method"],
        as_dict=True,
    )
    print(f"Item {ITEM}: {item}")

    do_not_use_batchwise = frappe.db.get_single_value(
        "Stock Settings", "do_not_use_batchwise_valuation"
    )
    print(f"Stock Settings.do_not_use_batchwise_valuation = {do_not_use_batchwise}")

    sles = frappe.db.sql(
        """SELECT name, posting_date, posting_time, creation, voucher_type, voucher_no,
                  actual_qty, qty_after_transaction, incoming_rate, outgoing_rate,
                  valuation_rate, stock_value, stock_value_difference,
                  batch_no, serial_and_batch_bundle, is_cancelled
           FROM `tabStock Ledger Entry`
           WHERE item_code=%s AND warehouse=%s
           ORDER BY posting_date, posting_time, creation""",
        (ITEM, WAREHOUSE), as_dict=True,
    )
    print(f"\n{len(sles)} Stock Ledger Entries for {ITEM} @ {WAREHOUSE}:")
    for s in sles:
        print(f"  {s.name}  {s.voucher_type} {s.voucher_no}  "
              f"posting={s.posting_date} {s.posting_time}  creation={s.creation}  "
              f"actual_qty={s.actual_qty}  qty_after={s.qty_after_transaction}  "
              f"in_rate={s.incoming_rate}  out_rate={s.outgoing_rate}  "
              f"val_rate={s.valuation_rate}  stock_value={s.stock_value}  "
              f"diff={s.stock_value_difference}  batch_no={s.batch_no!r}  "
              f"bundle={s.serial_and_batch_bundle}  cancelled={s.is_cancelled}")

        if s.serial_and_batch_bundle:
            bundle = frappe.db.get_value(
                "Serial and Batch Bundle", s.serial_and_batch_bundle,
                ["type_of_transaction", "total_qty", "total_amount", "avg_rate",
                 "posting_date", "posting_time", "docstatus", "is_cancelled"],
                as_dict=True,
            )
            print(f"    bundle {s.serial_and_batch_bundle}: {bundle}")
            children = frappe.db.sql(
                """SELECT batch_no, serial_no, qty, incoming_rate, stock_value_difference
                   FROM `tabSerial and Batch Entry`
                   WHERE parent=%s ORDER BY idx""",
                (s.serial_and_batch_bundle,), as_dict=True,
            )
            for c in children:
                print(f"      entry: {c}")


DN_BUNDLE = "854c356e84e98ffc728c"


def run_batch_valuation_trace():
    """Re-runs ERPNext's own BatchNoValuation for the DN's outward bundle
    (read-only — does NOT call set_incoming_rate(save=True), nothing is
    written) and prints its internal classification/state, so we see
    directly why BN17455 got incoming_rate=0 instead of guessing at the
    SQL from source.
    """
    from erpnext.stock.serial_batch_bundle import BatchNoValuation
    from erpnext.stock.utils import get_valuation_method

    bundle = frappe.get_doc("Serial and Batch Bundle", DN_BUNDLE)
    print(f"Bundle {DN_BUNDLE}: item={bundle.item_code} warehouse={bundle.warehouse} "
          f"type={bundle.type_of_transaction} posting={bundle.posting_date} {bundle.posting_time} "
          f"docstatus={bundle.docstatus} voucher_type={bundle.voucher_type} voucher_no={bundle.voucher_no}")

    for row in bundle.entries:
        b = frappe.db.get_value(
            "Batch", row.batch_no,
            ["use_batchwise_valuation", "creation"], as_dict=True,
        ) if row.batch_no else None
        print(f"  entry batch_no={row.batch_no!r} qty={row.qty} "
              f"incoming_rate={row.incoming_rate} batch_meta={b}")

    print(f"\nvaluation_method({bundle.item_code}) = {get_valuation_method(bundle.item_code)}")

    sle = bundle.get_sle_for_outward_transaction()
    print(f"sle context passed to BatchNoValuation: {dict(sle)}")

    sn_obj = BatchNoValuation(sle=sle, item_code=bundle.item_code, warehouse=bundle.warehouse)
    print(f"\nbatchwise_valuation_batches     = {sn_obj.batchwise_valuation_batches}")
    print(f"non_batchwise_valuation_batches  = {sn_obj.non_batchwise_valuation_batches}")
    print(f"available_qty                   = {dict(sn_obj.available_qty)}")
    print(f"stock_value_differece           = {dict(sn_obj.stock_value_differece)}")
    print(f"batch_avg_rate                  = {dict(sn_obj.batch_avg_rate)}")
