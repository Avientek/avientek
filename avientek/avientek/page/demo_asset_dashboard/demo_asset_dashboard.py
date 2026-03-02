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
		WHERE a.custom_is_demo_asset = 1 {company_clause}
	""", params)[0][0]

	out_for_demo = frappe.db.sql(f"""
		SELECT COUNT(*) FROM `tabAsset` a
		WHERE a.custom_is_demo_asset = 1 AND a.custom_dam_status = 'On Demo' {company_clause}
	""", params)[0][0]

	free = frappe.db.sql(f"""
		SELECT COUNT(*) FROM `tabAsset` a
		WHERE a.custom_is_demo_asset = 1 AND a.custom_dam_status = 'Free' {company_clause}
	""", params)[0][0]

	standby = frappe.db.sql(f"""
		SELECT COUNT(*) FROM `tabAsset` a
		WHERE a.custom_is_demo_asset = 1 AND a.custom_dam_status = 'Issued as Standby' {company_clause}
	""", params)[0][0]

	overdue = frappe.db.sql(f"""
		SELECT COUNT(*)
		FROM `tabAsset` a
		INNER JOIN `tabDemo Movement` dm ON dm.asset = a.name
		WHERE a.custom_is_demo_asset = 1
		  AND a.custom_dam_status = 'On Demo'
		  AND dm.movement_type = 'Move Out'
		  AND dm.status = 'Open'
		  AND dm.docstatus = 1
		  AND dm.expected_return_date < %(today)s
		  {company_clause}
	""", params)[0][0]

	open_rma = 0
	if frappe.db.table_exists("RMA Case"):
		rma_filters = {} if not company else {"company": company}
		open_rma = frappe.db.count("RMA Case", {**rma_filters, "status": ["not in", ["Closed", "Cancelled"]]})

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
			dm.requested_salesperson
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
			a.asset_value AS net_asset_value,
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
		FROM `tabAsset` a
		INNER JOIN `tabDemo Movement` dm ON dm.asset = a.name
		WHERE a.custom_is_demo_asset = 1
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
def create_demo_asset(item_code, asset_name, company, location, purchase_date,
		warehouse, stock_item_code=None, qty=1, asset_category=None,
		serial_no=None, batch_no=None):
	"""Create a Demo Asset via Asset Capitalization (consumes stock, creates Asset).
	item_code       = target fixed-asset item (is_fixed_asset=1)
	stock_item_code = inventory item to consume from warehouse (is_stock_item=1)
	"""
	# Validate target (fixed asset) item
	item = frappe.db.get_value("Item", item_code, ["asset_category", "item_name", "is_fixed_asset"], as_dict=True)
	if not item:
		frappe.throw(_("Target item {0} not found").format(item_code))

	resolved_category = asset_category or item.asset_category
	if not resolved_category:
		frappe.throw(_("Asset Category is required. Please select one in the dialog."))

	if not item.is_fixed_asset:
		frappe.db.set_value("Item", item_code, {
			"is_fixed_asset": 1,
			"asset_category": resolved_category,
		})
	elif not item.asset_category:
		frappe.db.set_value("Item", item_code, "asset_category", resolved_category)

	# The consumed stock item — defaults to target item if not provided separately
	consumed_item = stock_item_code or item_code

	# Create and submit Asset Capitalization — deducts stock and creates the Asset
	cap = frappe.new_doc("Asset Capitalization")
	cap.capitalization_method = "Create a new composite asset"
	cap.company = company
	cap.posting_date = purchase_date
	cap.target_item_code = item_code
	cap.target_asset_location = location
	stock_row = {
		"item_code": consumed_item,
		"warehouse": warehouse,
		"stock_qty": flt(qty),
	}
	if serial_no:
		stock_row["use_serial_batch_fields"] = 1
		stock_row["serial_no"] = serial_no
	if batch_no:
		stock_row["use_serial_batch_fields"] = 1
		stock_row["batch_no"] = batch_no
	cap.append("stock_items", stock_row)
	cap.insert(ignore_permissions=True)
	cap.submit()

	# Mark the resulting Asset as a demo asset
	asset_name_created = cap.target_asset
	if not asset_name_created:
		frappe.throw(_("Asset Capitalization submitted but no Asset was created. Please check the Asset Capitalization {0}.").format(cap.name))

	frappe.db.set_value("Asset", asset_name_created, {
		"custom_is_demo_asset": 1,
		"custom_dam_status": "Free",
	})

	# Override asset_name if provided
	if asset_name and asset_name != item.item_name:
		frappe.db.set_value("Asset", asset_name_created, "asset_name", asset_name)

	return asset_name_created
