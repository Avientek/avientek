"""#0601 (Jithin): Singapore company — GST was still set up at the old 7%.

Singapore GST has been 9% since 2024 and the 9% ledger exists
(2-05-01-28 - GST 9% - AETPLS), but the setup still pointed at the old one:

* Item Tax Template "Singapore Tax - AETPLS" (on ~35,000 items) said
  7% on the old ledger "GST - AETPLS". An item's template overrides the rate
  typed on the tax row, so a row showing 9% still calculated 7%
  (PO-AVS-26-00003 / 00004).
* The Sales and the Purchase tax template "Singapore Tax - AETPLS" had the
  same 7% row on the old ledger.

Point all three at the 9% ledger with 9%. Existing submitted documents are
not touched. Idempotent; does nothing if the company or ledger is missing.
"""
import frappe

ABBR = "AETPLS"
TEMPLATE = f"Singapore Tax - {ABBR}"
OLD_ACCOUNT = f"GST - {ABBR}"
NEW_ACCOUNT = f"2-05-01-28 - GST 9% - {ABBR}"
RATE = 9


def execute():
	if not frappe.db.exists("Account", NEW_ACCOUNT):
		return

	changed = []
	for row in frappe.get_all(
		"Item Tax Template Detail",
		filters={"parent": TEMPLATE, "parenttype": "Item Tax Template", "tax_type": OLD_ACCOUNT},
		pluck="name",
	):
		frappe.db.set_value("Item Tax Template Detail", row,
			{"tax_type": NEW_ACCOUNT, "tax_rate": RATE}, update_modified=False)
		changed.append("Item Tax Template")

	for child, parenttype in (
		("Sales Taxes and Charges", "Sales Taxes and Charges Template"),
		("Purchase Taxes and Charges", "Purchase Taxes and Charges Template"),
	):
		for row in frappe.get_all(
			child,
			filters={"parent": TEMPLATE, "parenttype": parenttype, "account_head": OLD_ACCOUNT},
			pluck="name",
		):
			frappe.db.set_value(child, row, {
				"account_head": NEW_ACCOUNT, "rate": RATE, "description": "GST 9%",
			}, update_modified=False)
			changed.append(parenttype)

	if changed:
		frappe.clear_cache(doctype="Item Tax Template")
		print(f"[#0601] Singapore GST set to 9% on: {', '.join(changed)}")
