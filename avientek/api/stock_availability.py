import json
import frappe
from frappe import _


@frappe.whitelist()
def get_batch_stock(item_codes, company=None):
	"""Return batch-wise stock availability for given item codes.

	Returns dict keyed by item_code, each value is a list of
	{warehouse, batch_no, qty} sorted by warehouse then batch.
	"""
	item_codes = json.loads(item_codes) if isinstance(item_codes, str) else item_codes
	if not item_codes:
		return {}

	company_filter = "AND sle.company = %(company)s" if company else ""

	data = frappe.db.sql("""
		SELECT
			sle.item_code,
			sle.warehouse,
			sle.batch_no,
			SUM(sle.actual_qty) AS qty
		FROM `tabStock Ledger Entry` sle
		WHERE sle.item_code IN %(item_codes)s
			AND sle.is_cancelled = 0
			{company_filter}
		GROUP BY sle.item_code, sle.warehouse, sle.batch_no
		HAVING SUM(sle.actual_qty) > 0
		ORDER BY sle.item_code, sle.warehouse, sle.batch_no
	""".format(company_filter=company_filter),
	{"item_codes": item_codes, "company": company}, as_dict=True)

	result = {ic: [] for ic in item_codes}
	for row in data:
		result.setdefault(row.item_code, []).append({
			"warehouse": row.warehouse,
			"batch_no": row.batch_no or "",
			"qty": row.qty,
		})

	return result
