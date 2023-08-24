import frappe
import json


# @frappe.whitelist()
# def get_previous_doc_rate_and_currency(doctype, child):
# 	po_details = []
# 	po_details = frappe.db.sql(
# 				f'''select
# 						po.currency,
# 						pi.rate
# 					from
# 						`tabPurchase Order` po left join
# 						`tabPurchase Order Item` pi on pi.parent = po.name
# 					where
# 						po.name="{doctype}" and pi.name="{child}"
# 					''', as_dict=1)
# 	return po_details

@frappe.whitelist()
def get_previous_doc_rate_and_currency(item_list):
	item_list = json.loads(item_list)
	for item in item_list:
		po_details = frappe.db.sql(
		f'''select
				po.currency,
				pi.rate
			from
				`tabPurchase Order` po left join
				`tabPurchase Order Item` pi on pi.parent = po.name
			where
				po.name="{item.get("doctype")}" and pi.name="{item.get("child")}"
			''', as_dict=1)
		if po_details:
			if po_details[0] and po_details[0].get("currency"):
				item["currency"] = po_details[0].get("currency")
			if po_details[0] and po_details[0].get("rate"):
				item["rate"] = po_details[0].get("rate")
	return item_list
