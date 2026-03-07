import frappe
from frappe import _


@frappe.whitelist()
def get_dashboard_stats(company=None):
	"""Return stat card values for the RMA dashboard."""
	filters = {"docstatus": 1}
	if company:
		filters["company"] = company

	total = frappe.db.count("RMA Case", filters)

	open_cases = frappe.db.count("RMA Case", {
		**filters,
		"status": ["not in", ["Closed", "Cancelled"]],
	})

	in_progress = frappe.db.count("RMA Case", {
		**filters,
		"status": "In Progress",
	})

	pending_parts = frappe.db.count("RMA Case", {
		**filters,
		"status": "Pending Parts",
	})

	sent_for_repair = frappe.db.count("RMA Case", {
		**filters,
		"status": "Sent for Repair",
	})

	closed = frappe.db.count("RMA Case", {
		**filters,
		"status": "Closed",
	})

	# Warranty stats
	wty_filters = {"docstatus": 1}
	if company:
		wty_filters["company"] = company

	under_warranty = frappe.db.count("Warranty List", {
		**wty_filters,
		"status": "Under Warranty",
	})

	expired_warranty = frappe.db.count("Warranty List", {
		**wty_filters,
		"status": "Expired",
	})

	return {
		"total": total,
		"open_cases": open_cases,
		"in_progress": in_progress,
		"pending_parts": pending_parts,
		"sent_for_repair": sent_for_repair,
		"closed": closed,
		"under_warranty": under_warranty,
		"expired_warranty": expired_warranty,
	}


@frappe.whitelist()
def get_rma_cases(company=None, status_filter="All"):
	"""Return RMA cases for the dashboard table."""
	company_clause = "AND rc.company = %(company)s" if company else ""
	status_clause = ""
	if status_filter and status_filter != "All":
		if status_filter == "Open":
			status_clause = "AND rc.status NOT IN ('Closed', 'Cancelled')"
		else:
			status_clause = "AND rc.status = %(status_filter)s"

	return frappe.db.sql(f"""
		SELECT
			rc.name,
			rc.status,
			rc.priority,
			rc.customer,
			rc.item_description,
			rc.fault_description,
			rc.warranty_status,
			rc.standby_unit,
			rc.rma_date,
			rc.closed_date,
			rc.demo_asset,
			rc.asset_serial_number,
			rc.country,
			rc.requested_salesperson,
			rc.company
		FROM `tabRMA Case` rc
		WHERE rc.docstatus = 1
		  {company_clause}
		  {status_clause}
		ORDER BY
			FIELD(rc.status, 'Open', 'In Progress', 'Pending Parts',
			      'Sent for Repair', 'Repaired', 'Replaced', 'Closed', 'Cancelled'),
			rc.rma_date DESC
	""", {
		"company": company,
		"status_filter": status_filter,
	}, as_dict=True)


@frappe.whitelist()
def get_warranties(company=None, status_filter="All"):
	"""Return Warranty List entries for the dashboard table."""
	company_clause = "AND wl.company = %(company)s" if company else ""
	status_clause = ""
	if status_filter and status_filter != "All":
		status_clause = "AND wl.status = %(status_filter)s"

	return frappe.db.sql(f"""
		SELECT
			wl.name,
			wl.status,
			wl.customer,
			wl.customer_name,
			wl.item_code,
			wl.item_name,
			wl.serial_no,
			wl.batch_no,
			wl.warranty_months,
			wl.warranty_start_date,
			wl.warranty_end_date,
			wl.days_remaining,
			wl.delivery_note,
			wl.company
		FROM `tabWarranty List` wl
		WHERE wl.docstatus = 1
		  {company_clause}
		  {status_clause}
		ORDER BY wl.warranty_end_date ASC
	""", {
		"company": company,
		"status_filter": status_filter,
	}, as_dict=True)
