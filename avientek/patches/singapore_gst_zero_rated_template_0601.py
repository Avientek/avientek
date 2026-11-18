"""#0601 (Jithin): Sales tax template for Singapore exports / zero-rated
sales — "Singapore GST 0% - <abbr>" on the existing GST 0% ledger. Used by
avientek.events.singapore_gst to fill the tax automatically. Idempotent.
"""
import frappe


def execute():
	for company in frappe.get_all("Company", filters={"country": "Singapore"}, fields=["name", "abbr"]):
		name = f"Singapore GST 0% - {company.abbr}"
		account = f"2-05-01-29 - GST 0% - {company.abbr}"
		if frappe.db.exists("Sales Taxes and Charges Template", name) or not frappe.db.exists("Account", account):
			continue
		doc = frappe.get_doc({
			"doctype": "Sales Taxes and Charges Template",
			"title": "Singapore GST 0%",
			"company": company.name,
			"taxes": [{
				"charge_type": "On Net Total",
				"account_head": account,
				"description": "GST 0%",
				"rate": 0,
			}],
		})
		doc.flags.ignore_permissions = True
		doc.insert()
		print(f"[#0601] created {doc.name}")
