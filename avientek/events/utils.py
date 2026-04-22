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


def normalize_gst_treatment_from_template(doc, method=None):
    """Pull `gst_treatment` onto each item row from its Item Tax Template
    before india_compliance's validate_transaction runs.

    Problem 1 (Apr 21): on a fresh Quotation, `gst_treatment` is a
    `fetch_from: item_tax_template.gst_treatment` field, but the fetch
    isn't guaranteed to have fired server-side when validate runs — rows
    come in blank / stale and the validator flags them as Non-GST.

    Problem 2 (Apr 22, reported by Sridhar — items IO17881, IO1789):
    legacy Item Tax Templates that pre-date india_compliance carry a
    real gst_rate and a populated `taxes` child table, but have no value
    in the `gst_treatment` field. Copying the blank field verbatim leaves
    the row as Non-GST and trips
    `validate_tax_accounts_for_non_gst` → "Cannot charge GST for Non GST
    Items" even though the template clearly represents taxable supply.

    Fix: when the template's gst_treatment is blank, INFER it:
      • gst_rate > 0          → Taxable
      • any child tax row rate > 0 → Taxable
    Otherwise leave the row alone so genuine Non-GST templates still
    enforce the compliance split.
    """
    if not getattr(doc, "items", None):
        return

    templates = {row.item_tax_template for row in doc.items if getattr(row, "item_tax_template", None)}
    if not templates:
        return

    # Read gst_treatment AND gst_rate from each template. gst_rate gives
    # us a fallback when the treatment field is blank on legacy templates.
    tpl_rows = frappe.get_all(
        "Item Tax Template",
        filters={"name": ("in", list(templates))},
        fields=["name", "gst_treatment", "gst_rate"],
    )
    if not tpl_rows:
        return

    # Child tax rates — a second fallback. If gst_treatment is blank AND
    # gst_rate is 0/null, but the template's `taxes` child table carries
    # a positive rate against some account, still infer Taxable.
    child_max_rate = {}
    child_rows = frappe.get_all(
        "Item Tax Template Detail",
        filters={"parent": ("in", list(templates))},
        fields=["parent", "tax_rate"],
    )
    for cr in child_rows:
        try:
            r = float(cr.get("tax_rate") or 0)
        except Exception:
            r = 0
        if r > child_max_rate.get(cr["parent"], 0):
            child_max_rate[cr["parent"]] = r

    resolved = {}
    for tpl in tpl_rows:
        treatment = tpl.get("gst_treatment")
        if not treatment:
            rate = 0
            try:
                rate = float(tpl.get("gst_rate") or 0)
            except Exception:
                rate = 0
            if rate > 0 or child_max_rate.get(tpl["name"], 0) > 0:
                treatment = "Taxable"
        resolved[tpl["name"]] = treatment

    for row in doc.items:
        tpl = getattr(row, "item_tax_template", None)
        if not tpl:
            continue
        tpl_treatment = resolved.get(tpl)
        if not tpl_treatment:
            continue
        current = getattr(row, "gst_treatment", None)
        if not current or current != tpl_treatment:
            row.gst_treatment = tpl_treatment


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
