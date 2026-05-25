"""Monkey-patch erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle.get_stock_ledgers_batches.

The "Pick Serial / Batch No" dialog (and any code path through
`get_auto_batch_nos` — `get_batch_qty`, `get_auto_data`, etc.)
consults two sources for batch availability:

  * `get_available_batches`     — bundle ledger; correct.
  * `get_stock_ledgers_batches` — legacy `SLE.batch_no` ledger; buggy.

The legacy helper sums `actual_qty` from `tabStock Ledger Entry`
grouped by `(batch_no, warehouse)` with no awareness of bundle-based
consumption. On sites where outward SLE rows carry `batch_no` for only
one of the consumed batches (with `actual_qty` equal to the total
outward), batches that were depleted *through* a multi-batch bundle
look untouched in this query. `update_available_batches` then adds the
stale legacy total onto the (correct) bundle balance, so emptied
batches reappear with phantom stock.

Fix: same shape as the dropdown patch — restrict the legacy ledger
helper to SLE rows that do not carry a bundle, so the bundle path is
the sole source of truth for those rows.

Applied at app import time by patching the function on the original
module so every existing call site (referenced by bare name within
the module) resolves to the patched version.
"""

import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import nowtime, today


def patched_get_stock_ledgers_batches(kwargs):
	from erpnext.stock.utils import get_combine_datetime

	stock_ledger_entry = frappe.qb.DocType("Stock Ledger Entry")
	batch_table = frappe.qb.DocType("Batch")

	query = (
		frappe.qb.from_(stock_ledger_entry)
		.inner_join(batch_table)
		.on(stock_ledger_entry.batch_no == batch_table.name)
		.select(
			stock_ledger_entry.warehouse,
			stock_ledger_entry.item_code,
			Sum(stock_ledger_entry.actual_qty).as_("qty"),
			stock_ledger_entry.batch_no,
			batch_table.expiry_date,
		)
		.where(
			(stock_ledger_entry.is_cancelled == 0)
			& (stock_ledger_entry.batch_no.isnotnull())
			& (stock_ledger_entry.serial_and_batch_bundle.isnull())
		)
		.groupby(stock_ledger_entry.batch_no, stock_ledger_entry.warehouse)
	)

	if kwargs.get("company"):
		query = query.where(stock_ledger_entry.company == kwargs.get("company"))

	for field in ["warehouse", "item_code", "batch_no"]:
		if not kwargs.get(field):
			continue

		if isinstance(kwargs.get(field), list):
			query = query.where(stock_ledger_entry[field].isin(kwargs.get(field)))
		else:
			query = query.where(stock_ledger_entry[field] == kwargs.get(field))

	if not kwargs.get("for_stock_levels"):
		query = query.where((batch_table.expiry_date >= today()) | (batch_table.expiry_date.isnull()))

	if kwargs.get("posting_date"):
		if kwargs.get("posting_time") is None:
			kwargs.posting_time = nowtime()

		timestamp_condition = stock_ledger_entry.posting_datetime <= get_combine_datetime(
			kwargs.posting_date, kwargs.posting_time
		)

		if kwargs.get("creation"):
			timestamp_condition = stock_ledger_entry.posting_datetime < get_combine_datetime(
				kwargs.posting_date, kwargs.posting_time
			)

			timestamp_condition |= (
				stock_ledger_entry.posting_datetime
				== get_combine_datetime(kwargs.posting_date, kwargs.posting_time)
			) & (stock_ledger_entry.creation < kwargs.creation)

		query = query.where(timestamp_condition)

	if kwargs.get("ignore_voucher_nos"):
		query = query.where(stock_ledger_entry.voucher_no.notin(kwargs.get("ignore_voucher_nos")))

	if kwargs.based_on == "LIFO":
		query = query.orderby(batch_table.creation, order=frappe.qb.desc)
	elif kwargs.based_on == "Expiry":
		query = query.orderby(batch_table.expiry_date)
	else:
		query = query.orderby(batch_table.creation)

	data = query.run(as_dict=True)
	batches = {}
	for d in data:
		key = (d.batch_no, d.warehouse)
		if key not in batches:
			batches[key] = d
		else:
			batches[key].qty += d.qty

	return batches


def install():
	from erpnext.stock.doctype.serial_and_batch_bundle import serial_and_batch_bundle as sbb_mod

	sbb_mod.get_stock_ledgers_batches = patched_get_stock_ledgers_batches
