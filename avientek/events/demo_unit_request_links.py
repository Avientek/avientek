import frappe
from frappe import _


def on_linked_doc_submit(doc, method=None):
	"""When a linked Asset Capitalization or Purchase Order is submitted,
	set the Demo Unit Request status to Fulfilled."""
	dur_name = doc.get("custom_demo_unit_request")
	if not dur_name:
		return

	dur = frappe.get_doc("Demo Unit Request", dur_name)
	if dur.docstatus == 1 and dur.status in ("Pending", "Approved"):
		dur.db_set("status", "Fulfilled")


def on_linked_doc_cancel(doc, method=None):
	"""When a linked Asset Capitalization or Purchase Order is cancelled,
	revert Demo Unit Request to Approved if no other submitted linked docs remain."""
	dur_name = doc.get("custom_demo_unit_request")
	if not dur_name:
		return

	dur = frappe.get_doc("Demo Unit Request", dur_name)
	if dur.docstatus != 1 or dur.status != "Fulfilled":
		return

	# Check if any other submitted Asset Capitalization or Purchase Order
	# still references this Demo Unit Request
	has_other_ac = frappe.db.exists(
		"Asset Capitalization",
		{"custom_demo_unit_request": dur_name, "docstatus": 1, "name": ("!=", doc.name)}
	) if doc.doctype == "Asset Capitalization" else frappe.db.exists(
		"Asset Capitalization",
		{"custom_demo_unit_request": dur_name, "docstatus": 1}
	)

	has_other_po = frappe.db.exists(
		"Purchase Order",
		{"custom_demo_unit_request": dur_name, "docstatus": 1, "name": ("!=", doc.name)}
	) if doc.doctype == "Purchase Order" else frappe.db.exists(
		"Purchase Order",
		{"custom_demo_unit_request": dur_name, "docstatus": 1}
	)

	if not has_other_ac and not has_other_po:
		dur.db_set("status", "Approved")
