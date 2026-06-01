"""Create a saved 'Quotation Item Detail' Report Builder report.

Sridhar 2026-06-01: Quotation Report View shows only parent-level rows
(one row per Quotation). Sales Order's Report View shows item-level
expanded rows (one row per Sales Order Item) because users have
pre-selected child-table columns. For Quotation parity, ship a saved
Report with both parent and Quotation Item columns so any user can
pick it from the 'Select Report' dropdown and immediately see
item-level rows.

The Report can be selected via /app/quotation/view/report → Select
Report → 'Quotation Item Detail'. Survives bench migrate. Idempotent.
"""

import json
import frappe


REPORT_NAME = "Quotation Item Detail"


REPORT_CONFIG = {
	"filters": [],
	"fields": [
		# Parent fields
		["name", "Quotation"],
		["workflow_state", "Quotation"],
		["status", "Quotation"],
		["transaction_date", "Quotation"],
		["customer", "Quotation"],
		["customer_name", "Quotation"],
		["company", "Quotation"],
		["currency", "Quotation"],
		["grand_total", "Quotation"],
		["base_grand_total", "Quotation"],
		# Child fields — drive item-level row expansion. part_number
		# sits right after item_code per Sridhar 2026-06-01.
		["item_code", "Quotation Item"],
		["part_number", "Quotation Item"],
		["item_name", "Quotation Item"],
		["qty", "Quotation Item"],
		["rate", "Quotation Item"],
		["amount", "Quotation Item"],
		["net_rate", "Quotation Item"],
		["net_amount", "Quotation Item"],
		["base_amount", "Quotation Item"],
		["base_net_amount", "Quotation Item"],
		["warehouse", "Quotation Item"],
		["brand", "Quotation Item"],
	],
	"order_by": "`tabQuotation`.`modified` desc",
	"add_totals_row": False,
	"page_length": 20,
	"group_by": None,
}


def execute():
	if frappe.db.exists("Report", REPORT_NAME):
		frappe.db.set_value(
			"Report", REPORT_NAME,
			{
				"json": json.dumps(REPORT_CONFIG),
				"ref_doctype": "Quotation",
				"report_type": "Report Builder",
				"is_standard": "No",
			},
			update_modified=False,
		)
		print(f"[create_quotation_item_detail_report] updated existing Report '{REPORT_NAME}'")
		return

	r = frappe.new_doc("Report")
	r.report_name = REPORT_NAME
	r.ref_doctype = "Quotation"
	r.report_type = "Report Builder"
	r.is_standard = "No"
	r.json = json.dumps(REPORT_CONFIG)
	r.insert(ignore_permissions=True)
	frappe.db.commit()
	print(f"[create_quotation_item_detail_report] created Report '{REPORT_NAME}'")
