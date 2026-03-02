import frappe
from frappe import _
from frappe.utils import today, date_diff, flt


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	summary = get_summary(data)
	return columns, data, None, None, summary


def get_columns():
	return [
		{
			"fieldname": "movement_name",
			"label": _("Movement"),
			"fieldtype": "Link",
			"options": "Demo Movement",
			"width": 160,
		},
		{
			"fieldname": "demo_asset",
			"label": _("Demo Asset"),
			"fieldtype": "Link",
			"options": "Demo Asset",
			"width": 150,
		},
		{
			"fieldname": "brand",
			"label": _("Brand"),
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"fieldname": "model",
			"label": _("Model"),
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"fieldname": "serial_number",
			"label": _("Serial No."),
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 180,
		},
		{
			"fieldname": "country",
			"label": _("Country"),
			"fieldtype": "Data",
			"width": 90,
		},
		{
			"fieldname": "requested_salesperson",
			"label": _("Salesperson"),
			"fieldtype": "Link",
			"options": "Sales Person",
			"width": 140,
		},
		{
			"fieldname": "movement_date",
			"label": _("Move Out Date"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "expected_return_date",
			"label": _("Expected Return"),
			"fieldtype": "Date",
			"width": 120,
		},
		{
			"fieldname": "days_out",
			"label": _("Days Out"),
			"fieldtype": "Int",
			"width": 90,
		},
		{
			"fieldname": "days_overdue",
			"label": _("Days Overdue"),
			"fieldtype": "Int",
			"width": 110,
		},
		{
			"fieldname": "status",
			"label": _("Status"),
			"fieldtype": "Data",
			"width": 90,
		},
		{
			"fieldname": "purpose",
			"label": _("Purpose"),
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"fieldname": "gross_asset_value",
			"label": _("Gross Value"),
			"fieldtype": "Currency",
			"options": "asset_currency",
			"width": 120,
		},
		{
			"fieldname": "accumulated_depreciation",
			"label": _("Depreciation"),
			"fieldtype": "Currency",
			"options": "asset_currency",
			"width": 120,
		},
		{
			"fieldname": "net_asset_value",
			"label": _("NAV"),
			"fieldtype": "Currency",
			"options": "asset_currency",
			"width": 120,
		},
		{
			"fieldname": "asset_currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"width": 80,
		},
	]


def get_data(filters):
	conditions = ["dm.docstatus = 1", "dm.movement_type = 'Move Out'", "dm.status IN ('Open', 'Overdue')"]
	values = {"today": today()}

	if filters.get("company"):
		conditions.append("dm.company = %(company)s")
		values["company"] = filters["company"]

	if filters.get("salesperson"):
		conditions.append("dm.requested_salesperson = %(salesperson)s")
		values["salesperson"] = filters["salesperson"]

	if filters.get("status") and filters["status"] != "All":
		conditions.append("dm.status = %(status)s")
		values["status"] = filters["status"]

	if filters.get("from_date"):
		conditions.append("dm.movement_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		conditions.append("dm.movement_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	where = " AND ".join(conditions)

	rows = frappe.db.sql(f"""
		SELECT
			dm.name              AS movement_name,
			dm.demo_asset,
			da.brand,
			da.model,
			da.serial_number,
			dm.customer,
			dm.country,
			dm.requested_salesperson,
			dm.movement_date,
			dm.expected_return_date,
			dm.purpose,
			dm.status,
			da.gross_asset_value,
			da.accumulated_depreciation,
			da.net_asset_value,
			da.asset_currency,
			DATEDIFF(%(today)s, dm.movement_date) AS days_out,
			CASE
				WHEN dm.expected_return_date IS NOT NULL AND dm.expected_return_date < %(today)s
				THEN DATEDIFF(%(today)s, dm.expected_return_date)
				ELSE 0
			END AS days_overdue
		FROM `tabDemo Movement` dm
		LEFT JOIN `tabDemo Asset` da ON da.name = dm.demo_asset
		WHERE {where}
		ORDER BY days_overdue DESC, dm.movement_date ASC
	""", values, as_dict=True)

	# Add row highlight for overdue
	for row in rows:
		if row.get("days_overdue") and row["days_overdue"] > 0:
			row["bold"] = 1

	return rows


def get_summary(data):
	total = len(data)
	overdue = sum(1 for r in data if r.get("days_overdue") and r["days_overdue"] > 0)
	total_nav = sum(flt(r.get("net_asset_value")) for r in data)

	currency = data[0].get("asset_currency", "AED") if data else "AED"

	return [
		{
			"value": total,
			"label": _("Total Out for Demo"),
			"datatype": "Int",
			"indicator": "blue",
		},
		{
			"value": overdue,
			"label": _("Overdue"),
			"datatype": "Int",
			"indicator": "red" if overdue else "green",
		},
		{
			"value": total_nav,
			"label": _("Total NAV at Risk"),
			"datatype": "Currency",
			"currency": currency,
			"indicator": "orange",
		},
	]
