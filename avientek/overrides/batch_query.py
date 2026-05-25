"""Override of erpnext.controllers.queries.get_batch_no.

ERPNext's batch autocomplete builds its result list from two queries —
one over legacy SLE.batch_no rows and one over Serial-and-Batch-Bundle
entries — and concatenates them. On sites where every modern SLE row
carries BOTH a legacy batch_no AND a serial_and_batch_bundle, the legacy
sub-query mis-attributes outward qty: a multi-batch outward bundle
produces one SLE row whose batch_no points to only one of the consumed
batches with actual_qty equal to the total outward. The other consumed
batches receive no debit on the legacy side. The bundle query nets them
correctly to zero and `HAVING qty != 0` filters them out — but the
legacy query reports them as still in stock, so they appear in the
dropdown with stale positive qty.

Fix: exclude legacy SLE rows that already carry a bundle so the bundle
sub-query is the sole source of truth for those rows.
"""

import frappe
from frappe.query_builder.functions import Concat, Sum
from frappe.utils import today

from erpnext.controllers.queries import (
	get_batches_from_serial_and_batch_bundle,
	get_empty_batches,
	get_filterd_batches,
)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_batch_no(doctype, txt, searchfield, start, page_len, filters):
	doctype = "Batch"
	meta = frappe.get_meta(doctype, cached=True)
	searchfields = meta.get_search_fields()
	page_len = 300

	batches = get_batches_from_stock_ledger_entries(searchfields, txt, filters, start, page_len)
	batches.extend(get_batches_from_serial_and_batch_bundle(searchfields, txt, filters, start, page_len))

	filtered_batches = get_filterd_batches(batches)

	if filters.get("is_inward"):
		filtered_batches.extend(get_empty_batches(filters, start, page_len, filtered_batches, txt))

	return filtered_batches


def get_batches_from_stock_ledger_entries(searchfields, txt, filters, start=0, page_len=100):
	stock_ledger_entry = frappe.qb.DocType("Stock Ledger Entry")
	batch_table = frappe.qb.DocType("Batch")

	expiry_date = filters.get("posting_date") or today()

	query = (
		frappe.qb.from_(stock_ledger_entry)
		.inner_join(batch_table)
		.on(batch_table.name == stock_ledger_entry.batch_no)
		.select(
			stock_ledger_entry.batch_no,
			Sum(stock_ledger_entry.actual_qty).as_("qty"),
		)
		.where(stock_ledger_entry.is_cancelled == 0)
		.where(
			(stock_ledger_entry.item_code == filters.get("item_code"))
			& (batch_table.disabled == 0)
			& (stock_ledger_entry.batch_no.isnotnull())
			& (stock_ledger_entry.serial_and_batch_bundle.isnull())
		)
		.groupby(stock_ledger_entry.batch_no, stock_ledger_entry.warehouse)
		.having(Sum(stock_ledger_entry.actual_qty) != 0)
		.offset(start)
		.limit(page_len)
	)

	if not filters.get("include_expired_batches"):
		query = query.where((batch_table.expiry_date >= expiry_date) | (batch_table.expiry_date.isnull()))

	query = query.select(
		Concat("MFG-", batch_table.manufacturing_date).as_("manufacturing_date"),
		Concat("EXP-", batch_table.expiry_date).as_("expiry_date"),
	)

	if filters.get("warehouse"):
		query = query.where(stock_ledger_entry.warehouse == filters.get("warehouse"))

	for field in searchfields:
		query = query.select(batch_table[field])

	if txt:
		txt_condition = batch_table.name.like(f"%{txt}%")
		for field in [*searchfields, "name"]:
			txt_condition |= batch_table[field].like(f"%{txt}%")

		query = query.where(txt_condition)

	return query.run(as_list=1) or []
