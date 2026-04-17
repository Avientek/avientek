import frappe
import json


def fill_missing_item_defaults(doc, method=None):
    """Server-side safety net for CSV/Excel/API-added rows that only have
    item_code populated. Fetches item_name / uom / stock_uom / description
    from Item master so mandatory validation doesn't fail.

    Runs as a before_validate doc_event on every transaction doctype with an
    items child table (Quotation, SO, DN, SI, PO, PI, PR, etc.).
    """
    tables = []
    for fieldname in ("items", "custom_service_items", "optional_items"):
        rows = doc.get(fieldname)
        if rows:
            tables.extend(rows)

    needs = [it for it in tables
             if getattr(it, "item_code", None)
             and (not getattr(it, "item_name", None) or not getattr(it, "uom", None))]
    if not needs:
        return

    codes = list({it.item_code for it in needs})
    rows = frappe.get_all(
        "Item",
        filters={"name": ["in", codes]},
        fields=["name", "item_name", "stock_uom", "description"],
    )
    by_code = {r["name"]: r for r in rows}

    for it in needs:
        src = by_code.get(it.item_code)
        if not src:
            continue
        if not getattr(it, "item_name", None):
            it.item_name = src["item_name"]
        if not getattr(it, "uom", None):
            it.uom = src["stock_uom"]
        if not getattr(it, "stock_uom", None):
            it.stock_uom = src["stock_uom"]
        if not getattr(it, "description", None):
            it.description = src["description"] or src["item_name"]
        if not getattr(it, "conversion_factor", None):
            it.conversion_factor = 1


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
