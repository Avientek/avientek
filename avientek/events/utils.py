import frappe


@frappe.whitelist()
def get_previous_doc_rate_and_currency(doctype, child):
	po_details = []
	po_details = frappe.db.sql(
				f'''select
						po.currency,
						pi.rate
					from
						`tabPurchase Order` po left join
						`tabPurchase Order Item` pi on pi.parent = po.name
					where
						po.name="{doctype}" and pi.name="{child}"
					''', as_dict=1)
	return po_details
