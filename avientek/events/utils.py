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

    # Sammish 2026-05-15: cross-company carry-over fix.
    # When a doc is created via mapping from another company's source
    # (e.g. PO-AT-26-00126 in Avientek Trading WLL → GRN-KSA-26-00082
    # in Avientek KSA), the source item rows arrive with their original
    # item_tax_template pointing at the SOURCE company's tax template
    # ("UAE VAT 5% - AETL" on a KSA Purchase Receipt). The receipt's
    # parent tax template ("KSA VAT 15% - KSA") then computes rate=0
    # because the per-item template doesn't define a rate for the KSA
    # VAT account → tax silently drops to zero.
    # Detect items whose existing template belongs to a DIFFERENT
    # company than doc.company and clear them so the re-pick loop
    # below assigns the right one.
    if doc.get("company"):
        for it in doc.items:
            tpl = getattr(it, "item_tax_template", None)
            if not tpl:
                continue
            tpl_company = frappe.db.get_value("Item Tax Template", tpl, "company")
            if tpl_company and tpl_company != doc.company:
                it.item_tax_template = None

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
            # Only accept templates whose suffix matches doc.company's abbr.
            for t in candidates:
                if not t:
                    continue
                if t.endswith(f" - {abbr}") or t.endswith(f"-{abbr}"):
                    picked = t
                    break
            # Sammish 2026-05-15: when no matching-abbr template exists
            # in the Item's tax table, LEAVE BLANK. The previous
            # candidates[0] fallback was unsafe — it re-assigned a
            # cross-company template (e.g. picked "UAE VAT 5% - A" on
            # a KSA receipt when the Item Master only had UAE/AETPL/
            # AETL/AK/EWCIT templates configured). ERPNext's tax calc
            # then computed 0% per item because the cross-company
            # template had no row for the parent doc's tax account.
            # Leaving item_tax_template blank lets ERPNext fall back
            # to the parent document's tax row rate (e.g. KSA VAT 15%
            # - KSA's 15%), which is the correct behaviour.
        elif candidates:
            # No company on the doc — accept the first candidate as
            # a best-effort default (preserves pre-2026-05-15 behaviour
            # for doctypes without a company link).
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


# Sridhar/Jithin 2026-06-12: India Sales Invoices, Quotations and SOs
# saved without picking a `taxes_and_charges` template come out with
# Total Taxes = 0 — Customer-visible bug: LTD-26-27-00382 (In-Sync
# Solutions) saved with grand_total=₹5,700 and ZERO GST.
#
# Root cause is upstream in india_compliance:
#   gst_india/overrides/transaction.py:1640 ItemGSTTreatment.set()
#       has_gst_accounts = any(row.gst_tax_type in TAX_TYPES
#                              for row in self.doc.taxes)
#       if not has_gst_accounts:
#           self.set_for_no_taxes()
#       ...
#   set_for_no_taxes() forces EVERY item.gst_treatment = "Nil-Rated"
#   (line 1653). Nil-Rated → 0% regardless of the item_tax_template
#   ("GST 18% - AETPL" with gst_treatment='Taxable' in our case).
#
# Our `normalize_gst_treatment_from_template` (earlier in this file)
# correctly sets gst_treatment='Taxable' on before_validate. But
# india_compliance's hook runs LATER and overrides it because the
# taxes table is empty.
#
# Avientek has 0 Tax Rules configured for the India company, so
# ERPNext's standard auto-resolution from tax_category never fires.
# Without a template, the taxes child stays empty, india_compliance
# stamps Nil-Rated, GST = 0. This hook is the missing layer: when an
# India-company sales doc is saved without taxes_and_charges, pick
# the right template based on intra-state vs inter-state, populate
# the taxes child from the template's rows. india_compliance then
# sees real GST accounts on doc.taxes and lets our Taxable treatment
# survive.
_AETPL_INDIA = "Avientek Electronics Trading PVT. LTD"
_AETPL_INSTATE_TEMPLATE = "Output GST In-state - AETPL"
_AETPL_OUTSTATE_TEMPLATE = "Output GST Out-state - AETPL"
_INDIA_GST_DOCTYPES = {"Quotation", "Sales Order", "Sales Invoice"}


def autofill_india_sales_taxes_template(doc, method=None):
    """Auto-pick AETPL's GST In-state vs Out-state template when an
    India sales doc is saved without taxes_and_charges set.

    Wired on before_validate for Quotation / Sales Order / Sales
    Invoice via hooks.py. NO-OP for every other company.
    """
    if doc.doctype not in _INDIA_GST_DOCTYPES:
        return
    if doc.get("company") != _AETPL_INDIA:
        return
    if doc.get("taxes_and_charges"):
        return  # user / mapper already picked a template — respect it
    if doc.get("taxes"):
        return  # taxes already populated some other way — don't disturb

    # Intra-state vs inter-state via GSTIN state codes (first 2 chars
    # of GSTIN are the state code; place_of_supply also encodes it as
    # "NN-State Name").
    company_state = (doc.get("company_gstin") or "")[:2]
    pos_state = (doc.get("place_of_supply") or "")[:2]
    billing_state = (doc.get("billing_address_gstin") or "")[:2]

    # Prefer billing GSTIN over place_of_supply when both are set —
    # the billing address is the customer's actual registration; pos
    # can be overridden by users.
    customer_state = billing_state or pos_state
    if not company_state or not customer_state:
        # Missing data — can't decide. Don't guess; let downstream
        # validation flag the missing GSTIN.
        return

    template_name = (
        _AETPL_INSTATE_TEMPLATE if company_state == customer_state
        else _AETPL_OUTSTATE_TEMPLATE
    )

    # Make sure the template exists — config drift on prod has burnt
    # us before. Skip gracefully if it's gone instead of crashing the
    # save.
    if not frappe.db.exists("Sales Taxes and Charges Template", template_name):
        return

    doc.taxes_and_charges = template_name

    # Populate doc.taxes from the template's child rows directly
    # rather than calling Frappe's set_taxes (which sometimes bails
    # mid-validate). Each row carries the GST account + rate;
    # india_compliance's TAX_TYPES check now sees real GST accounts
    # on the doc and routes through set_default_treatment instead of
    # set_for_no_taxes — so Taxable survives.
    #
    # Field-list note: we read via `frappe.get_doc(...).taxes` rather
    # than `frappe.get_all("Sales Taxes and Charges", fields=...)`
    # because the named-field list silently breaks across Frappe
    # versions (e.g. `category` was dropped at some point on local;
    # smoke caught it 2026-06-12). Reading the doc gives us whatever
    # fields exist on this version; we just copy the safe subset.
    template_doc = frappe.get_doc("Sales Taxes and Charges Template", template_name)
    _SAFE_TAX_ROW_FIELDS = (
        "charge_type", "account_head", "description", "rate",
        "row_id", "included_in_print_rate", "cost_center",
        "add_deduct_tax",
    )
    for row in (template_doc.get("taxes") or []):
        new_row = {}
        for k in _SAFE_TAX_ROW_FIELDS:
            v = row.get(k)
            if v is not None:
                new_row[k] = v
        if new_row.get("account_head"):
            doc.append("taxes", new_row)


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
