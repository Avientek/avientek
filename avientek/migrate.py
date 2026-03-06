from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def after_migrate():
	make_property_setter(
		"Item", None, "search_fields", "item_name,description,item_group,customer_code,part_number", "Data", for_doctype="Doctype"
	)
	_deactivate_old_quotation_workflows()


def _deactivate_old_quotation_workflows():
	"""Deactivate old Quotation workflows when Quotation Final exists."""
	if not frappe.db.exists("Workflow", "Quotation Final"):
		return
	old_workflows = ["Quotation Margin Approval", "Quotation DocFlow", "Quotation"]
	for wf_name in old_workflows:
		if frappe.db.exists("Workflow", wf_name):
			wf = frappe.get_doc("Workflow", wf_name)
			if wf.is_active:
				wf.is_active = 0
				wf.save(ignore_permissions=True)
				frappe.logger().info(f"Deactivated old workflow: {wf_name}")
