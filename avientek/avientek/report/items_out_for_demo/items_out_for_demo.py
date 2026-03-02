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
			"fieldname": "asset",
			"label": _("Asset"),
			"fieldtype": "Link",
			"options": "Asset",
			"width": 150,
		},
		{
			"fieldname": "asset_name",
			"label": _("Asset Name"),
			"fieldtype": "Data",
			"width": 180,
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
			"fieldname": "purchase_value",
			"label": _("Purchase Value"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "current_value",
			"label": _("Current Value (NAV)"),
			"fieldtype": "Currency",
			"width": 140,
		},
	]


def get_data(filters):
	conditions = [
		"dm.docstatus = 1",
		"dm.movement_type = 'Move Out'",
		"dm.status IN ('Open', 'Overdue')",
		"a.custom_is_demo_asset = 1",
	]
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
			dm.name                  AS movement_name,
			dm.asset,
			a.asset_name,
			dm.customer,
			dm.country,
			dm.requested_salesperson,
			dm.movement_date,
			dm.expected_return_date,
			dm.purpose,
			dm.status,
			a.gross_purchase_amount  AS purchase_value,
			a.asset_value            AS current_value,
			DATEDIFF(%(today)s, dm.movement_date) AS days_out,
			CASE
				WHEN dm.expected_return_date IS NOT NULL AND dm.expected_return_date < %(today)s
				THEN DATEDIFF(%(today)s, dm.expected_return_date)
				ELSE 0
			END AS days_overdue
		FROM `tabDemo Movement` dm
		LEFT JOIN `tabAsset` a ON a.name = dm.asset
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
	total_nav = sum(flt(r.get("current_value")) for r in data)

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
			"label": _("Total Current Value at Risk"),
			"datatype": "Currency",
			"indicator": "orange",
		},
	]
