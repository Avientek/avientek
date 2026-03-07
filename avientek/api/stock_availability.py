import json
import frappe
from frappe import _


@frappe.whitelist()
def get_batch_stock(item_codes, company=None):
	"""Return batch-wise stock availability for given item codes.

	Handles both legacy SLE entries (batch_no on SLE) and ERPNext v15
	entries where batch info lives in Serial and Batch Bundle / Entry.

	Returns dict keyed by item_code, each value is a list of
	{warehouse, batch_no, qty} sorted by warehouse then batch.
	"""
	item_codes = json.loads(item_codes) if isinstance(item_codes, str) else item_codes
	if not item_codes:
		return {}

	company_filter = "AND sle.company = %(company)s" if company else ""

	data = frappe.db.sql("""
		SELECT item_code, warehouse, batch_no, SUM(qty) AS qty
		FROM (
			/* Legacy: batch_no stored directly on SLE */
			SELECT sle.item_code, sle.warehouse, sle.batch_no, sle.actual_qty AS qty
			FROM `tabStock Ledger Entry` sle
			WHERE sle.item_code IN %(item_codes)s
				AND sle.is_cancelled = 0
				AND IFNULL(sle.batch_no, '') != ''
				{cf}

			UNION ALL

			/* V15: batch via Serial and Batch Bundle → Serial and Batch Entry */
			SELECT sle.item_code, sbe.warehouse, sbe.batch_no, sbe.qty
			FROM `tabStock Ledger Entry` sle
			JOIN `tabSerial and Batch Bundle` sbb
				ON sbb.name = sle.serial_and_batch_bundle
			JOIN `tabSerial and Batch Entry` sbe
				ON sbe.parent = sbb.name
			WHERE sle.item_code IN %(item_codes)s
				AND sle.is_cancelled = 0
				AND IFNULL(sle.batch_no, '') = ''
				AND IFNULL(sle.serial_and_batch_bundle, '') != ''
				AND IFNULL(sbe.batch_no, '') != ''
				{cf}

			UNION ALL

			/* Non-batch stock (no batch_no and no SBB) */
			SELECT sle.item_code, sle.warehouse, '' AS batch_no, sle.actual_qty AS qty
			FROM `tabStock Ledger Entry` sle
			WHERE sle.item_code IN %(item_codes)s
				AND sle.is_cancelled = 0
				AND IFNULL(sle.batch_no, '') = ''
				AND IFNULL(sle.serial_and_batch_bundle, '') = ''
				{cf}
		) combined
		GROUP BY item_code, warehouse, batch_no
		HAVING SUM(qty) > 0
		ORDER BY item_code, warehouse, batch_no
	""".format(cf=company_filter),
	{"item_codes": item_codes, "company": company}, as_dict=True)

	result = {ic: [] for ic in item_codes}
	for row in data:
		result.setdefault(row.item_code, []).append({
			"warehouse": row.warehouse,
			"batch_no": row.batch_no or "",
			"qty": row.qty,
		})

	return result


@frappe.whitelist()
def get_fifo_batch(item_code, warehouse, company=None):
	"""Return the oldest batch with available stock (FIFO) for an item + warehouse.

	Picks the batch with the earliest manufacturing_date (or creation date).
	"""
	if not item_code or not warehouse:
		return None

	company_filter = "AND sle.company = %(company)s" if company else ""

	# Get batch-wise available qty for this item + warehouse
	batch_stock = frappe.db.sql("""
		SELECT batch_no, SUM(qty) AS qty
		FROM (
			SELECT sle.batch_no, sle.actual_qty AS qty
			FROM `tabStock Ledger Entry` sle
			WHERE sle.item_code = %(item_code)s
				AND sle.warehouse = %(warehouse)s
				AND sle.is_cancelled = 0
				AND IFNULL(sle.batch_no, '') != ''
				{cf}

			UNION ALL

			SELECT sbe.batch_no, sbe.qty
			FROM `tabStock Ledger Entry` sle
			JOIN `tabSerial and Batch Bundle` sbb
				ON sbb.name = sle.serial_and_batch_bundle
			JOIN `tabSerial and Batch Entry` sbe
				ON sbe.parent = sbb.name
			WHERE sle.item_code = %(item_code)s
				AND sbe.warehouse = %(warehouse)s
				AND sle.is_cancelled = 0
				AND IFNULL(sle.batch_no, '') = ''
				AND IFNULL(sle.serial_and_batch_bundle, '') != ''
				AND IFNULL(sbe.batch_no, '') != ''
				{cf}
		) combined
		GROUP BY batch_no
		HAVING SUM(qty) > 0
	""".format(cf=company_filter),
	{"item_code": item_code, "warehouse": warehouse, "company": company}, as_dict=True)

	if not batch_stock:
		return None

	batch_names = [b.batch_no for b in batch_stock]
	qty_map = {b.batch_no: b.qty for b in batch_stock}

	# Pick the oldest batch by manufacturing_date (FIFO)
	oldest = frappe.db.sql("""
		SELECT name, manufacturing_date, creation
		FROM `tabBatch`
		WHERE name IN %(batch_names)s AND disabled = 0
		ORDER BY IFNULL(manufacturing_date, creation) ASC
		LIMIT 1
	""", {"batch_names": batch_names}, as_dict=True)

	if not oldest:
		return None

	batch = oldest[0]
	return {
		"batch_no": batch.name,
		"qty": qty_map.get(batch.name, 0),
	}
