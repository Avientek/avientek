import frappe
from frappe import _
from frappe.utils import today, add_days, date_diff


@frappe.whitelist()
def get_dashboard_stats(company=None):
	"""Return all stat card values for the DAM dashboard."""
	filters = {}
	if company:
		filters["company"] = company

	total = frappe.db.count("Demo Asset", filters)
	out_for_demo = frappe.db.count("Demo Asset", {**filters, "status": "On Demo"})
	free = frappe.db.count("Demo Asset", {**filters, "status": "Free"})
	standby = frappe.db.count("Demo Asset", {**filters, "status": "Issued as Standby"})

	# Overdue: On Demo AND expected_return_date < today
	overdue_filters = {**filters, "status": "On Demo"}
	company_clause = "AND da.company = %(company)s" if company else ""
	overdue = frappe.db.sql("""
		SELECT COUNT(*)
		FROM `tabDemo Asset` da
		INNER JOIN `tabDemo Movement` dm ON dm.demo_asset = da.name
		WHERE da.status = 'On Demo'
		  AND dm.movement_type = 'Move Out'
		  AND dm.status = 'Open'
		  AND dm.docstatus = 1
		  AND dm.expected_return_date < %(today)s
		  {company_clause}
	""".format(company_clause=company_clause), {
		"today": today(),
		"company": company,
	})[0][0]

	open_rma = 0
	if frappe.db.table_exists("RMA Case"):
		rma_filters = {} if not company else {"company": company}
		open_rma = frappe.db.count("RMA Case", {**rma_filters, "status": ["not in", ["Closed"]]})

	return {
		"total": total,
		"out_for_demo": out_for_demo,
		"overdue": overdue,
		"free": free,
		"standby": standby,
		"open_rma": open_rma,
	}


@frappe.whitelist()
def get_overdue_assets(company=None):
	"""Return list of overdue demo assets (expected return date passed)."""
	company_clause = "AND da.company = %(company)s" if company else ""
	return frappe.db.sql("""
		SELECT
			da.name AS demo_asset,
			da.brand,
			da.model,
			da.serial_number,
			da.company,
			dm.customer,
			dm.movement_date,
			dm.expected_return_date,
			dm.requested_salesperson,
			DATEDIFF(%(today)s, dm.expected_return_date) AS days_overdue
		FROM `tabDemo Asset` da
		INNER JOIN `tabDemo Movement` dm ON dm.demo_asset = da.name
		WHERE da.status = 'On Demo'
		  AND dm.movement_type = 'Move Out'
		  AND dm.status = 'Open'
		  AND dm.docstatus = 1
		  AND dm.expected_return_date < %(today)s
		  {company_clause}
		ORDER BY days_overdue DESC
	""".format(company_clause=company_clause), {
		"today": today(),
		"company": company,
	}, as_dict=True)


@frappe.whitelist()
def get_recent_movements(company=None, limit=10):
	"""Return recent demo movements for the dashboard table."""
	company_clause = "AND dm.company = %(company)s" if company else ""
	return frappe.db.sql("""
		SELECT
			dm.name,
			dm.demo_asset,
			da.brand,
			da.model,
			dm.customer,
			dm.movement_date,
			dm.expected_return_date,
			dm.movement_type,
			dm.status,
			dm.requested_salesperson
		FROM `tabDemo Movement` dm
		LEFT JOIN `tabDemo Asset` da ON da.name = dm.demo_asset
		WHERE dm.docstatus = 1
		  {company_clause}
		ORDER BY dm.movement_date DESC
		LIMIT %(limit)s
	""".format(company_clause=company_clause), {
		"company": company,
		"limit": int(limit),
	}, as_dict=True)


@frappe.whitelist()
def get_items_out_for_demo(company=None):
	"""Return all assets currently out for demo with days outstanding."""
	company_clause = "AND da.company = %(company)s" if company else ""
	return frappe.db.sql("""
		SELECT
			da.name AS demo_asset,
			da.brand,
			da.model,
			da.serial_number,
			da.company,
			da.net_asset_value,
			da.asset_currency,
			dm.name AS movement_name,
			dm.customer,
			dm.movement_date,
			dm.expected_return_date,
			dm.requested_salesperson,
			dm.purpose,
			DATEDIFF(%(today)s, dm.movement_date) AS days_outstanding,
			CASE
				WHEN dm.expected_return_date < %(today)s THEN 1
				ELSE 0
			END AS is_overdue
		FROM `tabDemo Asset` da
		INNER JOIN `tabDemo Movement` dm ON dm.demo_asset = da.name
		WHERE da.status = 'On Demo'
		  AND dm.movement_type = 'Move Out'
		  AND dm.status IN ('Open', 'Overdue')
		  AND dm.docstatus = 1
		  {company_clause}
		ORDER BY is_overdue DESC, days_outstanding DESC
	""".format(company_clause=company_clause), {
		"today": today(),
		"company": company,
	}, as_dict=True)
