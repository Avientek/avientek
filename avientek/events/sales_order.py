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
			"Sales Taxes and Charges":{
				"doctype":"Sales Taxes and Charges",
			}
		},
		target_doc,
	)
	return target_doc


def update_eta_in_po(doc, method):
	for item in doc.items:
		if item.purchase_order:
			po = frappe.get_doc("Purchase Order", item.purchase_order)
			updated = False
			for po_item in po.items:
				if po_item.item_code == item.item_code:
					po_item.db_set("avientek_eta", item.avientek_eta)
					po_item.db_set("eta", item.eta)
					po.db_set("avientek_eta",item.avientek_eta)
					updated = True
			if updated:
				po.save()
