import frappe
from frappe.model.mapper import get_mapped_doc


@frappe.whitelist()
def create_proforma_invoice(source_name, target_doc=None, args=None):
    target_doc = get_mapped_doc(
		"Sales Order",
		source_name,
		{
			"Sales Order": {
				"doctype": "Avientek Proforma Invoice",
			},
			"Sales Order Item": {
				"doctype": "Proforma Invoice Item",
				"field_map": [
					# ["qty", "quantity"]
					# ["name","purchase_order_item"]
				],
				# "postprocess":update_item,
				# "condition": lambda doc: abs(doc.received_qty) <= abs(doc.qty),
			},
		},
		target_doc,
	)
    return target_doc