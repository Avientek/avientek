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


def autofill_item_tax_template(doc, required_company=None):
    """Try to auto-populate `item_tax_template` on every items row that
    has it blank, picking from the Item's own Item Tax child table.

    Preference order per item:
      1. A tax_template whose name suffix matches the Company abbreviation
         (e.g. "GST 18% - AETPL" for Avientek Electronics Trading PVT. LTD)
      2. First entry in the Item's taxes child table
      3. Leave blank

    If `required_company` is supplied and matches doc.company, any row
    still blank after auto-fill will raise frappe.throw — replicating the
    old behaviour but only when we truly couldn't resolve a template.
    Other companies skip the hard check.

    Called from validate_item_tax_template on Quotation, SO, SI, DN, PI,
    PR, PO. Fires BEFORE the legacy throw so Finance's repeated
    "Kindly choose Item Tax template for item X" errors on items that
    already have configured taxes simply stop appearing.
    """
    if not getattr(doc, "items", None):
        return

    abbr = ""
    if doc.get("company"):
        abbr = frappe.db.get_value("Company", doc.company, "abbr") or ""

    rows_to_fill = [it for it in doc.items if not getattr(it, "item_tax_template", None)]
    if not rows_to_fill:
        return

    codes = list({it.item_code for it in rows_to_fill if getattr(it, "item_code", None)})
    if not codes:
        return

    tax_rows = frappe.get_all(
        "Item Tax",
        filters={"parent": ["in", codes], "parenttype": "Item"},
        fields=["parent", "item_tax_template", "idx"],
        order_by="parent asc, idx asc",
    )
    tax_by_item = {}
    for tr in tax_rows:
        tax_by_item.setdefault(tr["parent"], []).append(tr["item_tax_template"])

    for it in rows_to_fill:
        candidates = tax_by_item.get(it.item_code) or []
        if not candidates:
            continue
        picked = None
        if abbr:
            for t in candidates:
                if not t:
                    continue
                if t.endswith(f" - {abbr}") or t.endswith(f"-{abbr}"):
                    picked = t
                    break
        if not picked:
            picked = candidates[0]
        if picked:
            it.item_tax_template = picked

    # Hard gate, only for the company that used to throw.
    if required_company and doc.get("company") == required_company:
        missing = [it for it in doc.items if not getattr(it, "item_tax_template", None)]
        if missing:
            row = missing[0]
            frappe.throw(
                frappe._("Kindly choose Item Tax template for item: {0} in Row# {1}").format(
                    row.item_code, row.idx
                )
            )


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
