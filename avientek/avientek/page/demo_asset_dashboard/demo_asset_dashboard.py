import frappe
from frappe import _
from frappe.utils import today, add_days, date_diff, flt, cint


@frappe.whitelist()
def get_dashboard_stats(company=None):
	"""Return all stat card values for the DAM dashboard."""
	company_clause = "AND a.company = %(company)s" if company else ""
	params = {"today": today(), "company": company}

	total = frappe.db.sql(f"""
		SELECT COUNT(*) FROM `tabAsset` a
		WHERE a.custom_is_demo_asset = 1 AND a.docstatus < 2 {company_clause}
	""", params)[0][0]

	out_for_demo = frappe.db.sql(f"""
		SELECT COUNT(*) FROM `tabAsset` a
		WHERE a.custom_is_demo_asset = 1 AND a.docstatus < 2 AND a.custom_dam_status = 'On Demo' {company_clause}
	""", params)[0][0]

	free = frappe.db.sql(f"""
		SELECT COUNT(*) FROM `tabAsset` a
		WHERE a.custom_is_demo_asset = 1 AND a.docstatus < 2 AND a.custom_dam_status = 'Free' {company_clause}
	""", params)[0][0]

	standby = frappe.db.sql(f"""
		SELECT COUNT(*) FROM `tabAsset` a
		WHERE a.custom_is_demo_asset = 1 AND a.docstatus < 2 AND a.custom_dam_status = 'Issued as Standby' {company_clause}
	""", params)[0][0]

	overdue = frappe.db.sql(f"""
		SELECT COUNT(*)
		FROM `tabAsset` a
		INNER JOIN `tabDemo Movement` dm ON dm.asset = a.name
		WHERE a.custom_is_demo_asset = 1
		  AND a.docstatus < 2
		  AND a.custom_dam_status = 'On Demo'
		  AND dm.movement_type = 'Move Out'
		  AND dm.status = 'Open'
		  AND dm.docstatus = 1
		  AND dm.expected_return_date < %(today)s
		  {company_clause}
	""", params)[0][0]

	return {
		"total": total,
		"out_for_demo": out_for_demo,
		"overdue": overdue,
		"free": free,
		"standby": standby,
	}


@frappe.whitelist()
def get_overdue_assets(company=None):
	"""Return list of overdue demo assets (expected return date passed)."""
	company_clause = "AND a.company = %(company)s" if company else ""
	return frappe.db.sql(f"""
		SELECT
			a.name AS asset,
			a.asset_name,
			a.company,
			dm.customer,
			dm.movement_date,
			dm.expected_return_date,
			dm.requested_salesperson,
			DATEDIFF(%(today)s, dm.expected_return_date) AS days_overdue
		FROM `tabAsset` a
		INNER JOIN `tabDemo Movement` dm ON dm.asset = a.name
		WHERE a.custom_is_demo_asset = 1
		  AND a.docstatus < 2
		  AND a.custom_dam_status = 'On Demo'
		  AND dm.movement_type = 'Move Out'
		  AND dm.status = 'Open'
		  AND dm.docstatus = 1
		  AND dm.expected_return_date < %(today)s
		  {company_clause}
		ORDER BY days_overdue DESC
	""", {
		"today": today(),
		"company": company,
	}, as_dict=True)


@frappe.whitelist()
def get_recent_movements(company=None, limit=10):
	"""Return recent demo movements for the dashboard table."""
	company_clause = "AND dm.company = %(company)s" if company else ""
	return frappe.db.sql(f"""
		SELECT
			dm.name,
			dm.asset,
			a.asset_name,
			dm.customer,
			dm.movement_date,
			dm.expected_return_date,
			dm.movement_type,
			dm.status,
			dm.requested_salesperson,
			a.custom_dam_status
		FROM `tabDemo Movement` dm
		LEFT JOIN `tabAsset` a ON a.name = dm.asset
		WHERE dm.docstatus = 1
		  {company_clause}
		ORDER BY dm.movement_date DESC
		LIMIT %(limit)s
	""", {
		"company": company,
		"limit": int(limit),
	}, as_dict=True)


@frappe.whitelist()
def get_items_out_for_demo(company=None):
	"""Return all assets currently out for demo with days outstanding."""
	company_clause = "AND a.company = %(company)s" if company else ""
	return frappe.db.sql(f"""
		SELECT
			a.name AS asset,
			a.asset_name,
			a.company,
			a.gross_purchase_amount,
			a.value_after_depreciation AS net_asset_value,
			dm.name AS movement_name,
			dm.customer,
			dm.contact_person,
			dm.mobile,
			dm.email,
			dm.country,
			dm.serial_number,
			dm.movement_date,
			dm.expected_return_date,
			dm.requested_salesperson,
			dm.purpose,
			DATEDIFF(%(today)s, dm.movement_date) AS days_outstanding,
			CASE
				WHEN dm.expected_return_date < %(today)s THEN 1
				ELSE 0
			END AS is_overdue
		FROM `tabAsset` a
		INNER JOIN `tabDemo Movement` dm ON dm.asset = a.name
		WHERE a.custom_is_demo_asset = 1
		  AND a.docstatus < 2
		  AND a.custom_dam_status = 'On Demo'
		  AND dm.movement_type = 'Move Out'
		  AND dm.status IN ('Open', 'Overdue')
		  AND dm.docstatus = 1
		  {company_clause}
		ORDER BY is_overdue DESC, days_outstanding DESC
	""", {
		"today": today(),
		"company": company,
	}, as_dict=True)


@frappe.whitelist()
def get_demo_assets(company=None, status_filter="All"):
	"""Return all demo assets with brand, serial, location, days out info."""
	company_clause = "AND a.company = %(company)s" if company else ""
	status_clause = ""
	if status_filter and status_filter != "All":
		status_clause = "AND a.custom_dam_status = %(status_filter)s"

	return frappe.db.sql(f"""
		SELECT
			a.name,
			a.asset_name,
			a.item_code,
			i.brand,
			a.company,
			a.location,
			a.custom_dam_status,
			a.custom_dam_customer,
			a.custom_serial_no,
			a.custom_part_no,
			a.asset_owner_company,
			a.custom_dam_country,
			a.custom_dam_notes,
			dm_latest.serial_number AS movement_serial_number,
			dm_latest.movement_date,
			dm_latest.expected_return_date,
			CASE
				WHEN a.custom_dam_status IN ('On Demo', 'Issued as Standby')
				 AND dm_latest.movement_date IS NOT NULL
				THEN DATEDIFF(%(today)s, dm_latest.movement_date)
				ELSE NULL
			END AS days_out,
			CASE
				WHEN a.custom_dam_status = 'On Demo'
				 AND dm_latest.expected_return_date IS NOT NULL
				 AND dm_latest.expected_return_date < %(today)s
				THEN 1
				ELSE 0
			END AS is_overdue
		FROM `tabAsset` a
		LEFT JOIN `tabItem` i ON i.name = a.item_code
		LEFT JOIN `tabDemo Movement` dm_latest ON dm_latest.name = (
			SELECT dm1.name
			FROM `tabDemo Movement` dm1
			WHERE dm1.asset = a.name
			  AND dm1.movement_type = 'Move Out'
			  AND dm1.status IN ('Open', 'Overdue')
			  AND dm1.docstatus = 1
			ORDER BY dm1.movement_date DESC
			LIMIT 1
		)
		WHERE a.custom_is_demo_asset = 1
		  AND a.docstatus < 2
		  {company_clause}
		  {status_clause}
		ORDER BY
			CASE WHEN a.custom_dam_status = 'On Demo' THEN 0
			     WHEN a.custom_dam_status = 'Issued as Standby' THEN 1
			     ELSE 2
			END,
			a.name ASC
	""", {
		"today": today(),
		"company": company,
		"status_filter": status_filter,
	}, as_dict=True)


