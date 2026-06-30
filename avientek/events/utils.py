import frappe
import json
from frappe import _


def validate_payment_terms_mandatory(doc, method=None):
	"""Block submit of Sales Order / Sales Invoice without Payment Terms.

	Rahul 2026-06-30: Payment Terms must be mandatory on SO & Invoice.
	Enforced at SUBMIT time (not save) so drafts and data-imports can still
	be saved, and intercompany / internal auto-created documents are exempt
	so the intercompany SO/PO/SI makers don't break (those are generated
	without terms by ERPNext).

	Accepts either a Payment Terms Template or manually-entered Payment
	Schedule rows.
	"""
	# Exempt intercompany / internal documents (auto-created without terms).
	if doc.get("is_internal_customer"):
		return
	if doc.get("inter_company_order_reference") or doc.get("inter_company_invoice_reference"):
		return

	if not (doc.get("payment_terms_template") or doc.get("payment_schedule")):
		frappe.throw(
			_("Payment Terms is mandatory. Please set a Payment Terms Template before submitting."),
			title=_("Payment Terms Required"),
		)


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
_AETPL_TEMPLATES = (_AETPL_INSTATE_TEMPLATE, _AETPL_OUTSTATE_TEMPLATE)
_INDIA_GST_DOCTYPES = {"Quotation", "Sales Order", "Sales Invoice"}

# Fields safe to copy from a Sales Taxes and Charges template row across
# Frappe versions. `category` was dropped on some versions — exclude
# the auto-set audit fields and any unknown-future fields. Smoke
# 2026-06-12 caught the version-drift on `category`.
_SAFE_TAX_ROW_FIELDS = (
    "charge_type", "account_head", "description", "rate",
    "row_id", "included_in_print_rate", "cost_center",
    "add_deduct_tax",
)


def _resolve_aetpl_state_pair(doc):
    """Return (company_state_code, customer_state_code) — both two-char
    strings or '' if undeterminable.

    Resilient to the `before_validate` race: at hook firing time the
    Sales Invoice / Quotation may not yet have GSTIN-related fields
    populated (the form posts a doc dict where client-side fetches
    haven't completed, OR set_missing_values hasn't run yet on this
    code path). When that happens, call _get_party_details ourselves to
    derive company_gstin, billing_address_gstin and place_of_supply
    from the chosen customer + address. Stamp them on the doc so
    downstream validators see them too.
    """
    company_gstin = doc.get("company_gstin") or ""
    billing_gstin = doc.get("billing_address_gstin") or ""
    pos = doc.get("place_of_supply") or ""

    needs_fetch = (not company_gstin) or (not billing_gstin and not pos)
    if needs_fetch and doc.get("customer"):
        try:
            from erpnext.accounts.party import _get_party_details

            pd = _get_party_details(
                party=doc.customer,
                party_type="Customer",
                company=doc.company,
                posting_date=doc.get("posting_date"),
                doctype=doc.doctype,
                party_address=doc.get("customer_address"),
                shipping_address=doc.get("shipping_address_name"),
                ignore_permissions=True,
            ) or {}

            if not company_gstin:
                company_gstin = pd.get("company_gstin") or ""
                if company_gstin and not doc.get("company_gstin"):
                    doc.company_gstin = company_gstin
            if not billing_gstin:
                billing_gstin = pd.get("billing_address_gstin") or ""
                if billing_gstin and not doc.get("billing_address_gstin"):
                    doc.billing_address_gstin = billing_gstin
            if not pos:
                pos = pd.get("place_of_supply") or ""
                if pos and not doc.get("place_of_supply"):
                    doc.place_of_supply = pos
            if not doc.get("customer_address") and pd.get("customer_address"):
                doc.customer_address = pd.get("customer_address")
        except Exception:
            # _get_party_details can fail mid-form-build (e.g. customer
            # not saved, address pending). Don't crash the save —
            # fall through and let the early-return below trigger.
            pass

    # Prefer billing GSTIN over place_of_supply when both are set —
    # billing address is the customer's actual registration; pos can be
    # overridden by users.
    customer_state = (billing_gstin or "")[:2] or (pos or "")[:2]
    return (company_gstin or "")[:2], customer_state


def _apply_template_rows(doc, template_name):
    """Replace doc.taxes with rows copied from the named template.

    Reads via frappe.get_doc(...).taxes (not get_all with explicit
    fields) so the copy survives Frappe field-list drift (`category`
    field dropped on some versions). Audit fields (name, idx, parent,
    creation, etc.) are NOT copied — Frappe stamps fresh ones on save.
    """
    template_doc = frappe.get_doc("Sales Taxes and Charges Template", template_name)
    # Clear in-place rather than `doc.taxes = []` so both real Frappe
    # Documents AND test fakes that proxy reads through `.get("taxes")`
    # see the empty state. Frappe Document.taxes IS the list, so
    # `[:] = []` is a legitimate clear.
    existing = doc.get("taxes")
    if isinstance(existing, list):
        existing[:] = []
    for row in (template_doc.get("taxes") or []):
        new_row = {}
        for k in _SAFE_TAX_ROW_FIELDS:
            v = row.get(k)
            if v is not None:
                new_row[k] = v
        if new_row.get("account_head"):
            doc.append("taxes", new_row)


def autofill_india_sales_taxes_template(doc, method=None, *args, **kwargs):
    """Auto-pick + auto-correct AETPL's GST In-state vs Out-state
    template on India sales docs. Resilient across all save paths.

    Wired on before_validate for Quotation / Sales Order / Sales
    Invoice via hooks.py. NO-OP for every other company.

    Three-layer defense — designed so a user can never end up with the
    "Cannot charge CGST/SGST for inter-state supplies" india_compliance
    error or with ₹0 GST on an AETPL sale:

    Layer 1 (fresh fill): doc has no template set → resolve state pair
        (lazy-fetch GSTINs via _get_party_details if missing) → pick
        In-state for matching state codes, Out-state otherwise → copy
        template rows into doc.taxes.

    Layer 2 (auto-correct WRONG AETPL pick): doc already has one of
        the AETPL templates but it's the WRONG direction for the
        resolved state pair (user picked In-state on an inter-state
        sale, or vice-versa, or a mapper from PI/SO carried over
        across a state-mismatched company) → swap to the correct
        template + msgprint(orange) so the user sees what changed and
        why. india_compliance's downstream validate then sees a
        matching template + GSTIN pair and passes.

    Layer 3 (respect): doc has a NON-AETPL template (custom Export
        GST, SEZ, Reverse Charge, etc.) → no-op. Trust the user's
        explicit pick; india_compliance's own validation will catch
        misuse.

    Hook signature is `(doc, method=None, *args, **kwargs)` to absorb
    Frappe's Document.hook composer extras — see
    [[feedback-frappe-doc-hook-composer-3arg-shape]].
    """
    if doc.doctype not in _INDIA_GST_DOCTYPES:
        return
    if doc.get("company") != _AETPL_INDIA:
        return

    company_state, customer_state = _resolve_aetpl_state_pair(doc)
    if not company_state or not customer_state:
        # Genuinely no GSTIN data — let india_compliance flag the
        # missing GSTIN rather than guessing.
        return

    is_intra_state = company_state == customer_state
    correct_template = (
        _AETPL_INSTATE_TEMPLATE if is_intra_state else _AETPL_OUTSTATE_TEMPLATE
    )

    if not frappe.db.exists("Sales Taxes and Charges Template", correct_template):
        # Template config drift — skip gracefully rather than crashing
        # the save. Will surface as ₹0 GST and our smoke catches it.
        return

    current = doc.get("taxes_and_charges")

    if current and current not in _AETPL_TEMPLATES:
        # Layer 3 — user explicitly picked a non-AETPL template
        # (Export GST, SEZ, etc.). Trust them; do nothing.
        return

    if current == correct_template:
        # Layer 1 already done on a previous save / already correct.
        # If somehow taxes child is empty (mapper edge case), refill.
        if not doc.get("taxes"):
            _apply_template_rows(doc, correct_template)
        return

    if current in _AETPL_TEMPLATES and current != correct_template:
        # Layer 2 — WRONG AETPL template picked. Auto-correct.
        _apply_template_rows(doc, correct_template)
        doc.taxes_and_charges = correct_template
        try:
            frappe.msgprint(
                frappe._(
                    "GST template auto-corrected: <b>{0}</b> → <b>{1}</b>. "
                    "Reason: detected <b>{2}-state</b> supply "
                    "(company GSTIN state code <b>{3}</b>, "
                    "customer GSTIN / place-of-supply state code <b>{4}</b>). "
                    "The wrong template would have raised "
                    "“Cannot charge CGST/SGST for inter-state supplies”."
                ).format(
                    current, correct_template,
                    "intra" if is_intra_state else "inter",
                    company_state, customer_state,
                ),
                indicator="orange",
                title=frappe._("Auto-corrected GST template"),
                alert=True,
            )
        except Exception:
            pass
        return

    # Layer 1 — fresh fill: no template, no taxes child rows.
    if doc.get("taxes"):
        # Some other hook populated taxes without a template — leave
        # alone, don't disturb their intentional setup.
        return

    doc.taxes_and_charges = correct_template
    _apply_template_rows(doc, correct_template)


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

# ---------------------------------------------------------------------
# Date sanity validator
# ---------------------------------------------------------------------
#
# Sridhar / Jithin 2026-06-12 + 2026-06-15: SO-LTD-25-00302 was saved
# with transaction_date = '0205-03-31' (year 205 CE instead of 2025).
# Standard ERPNext + Frappe accept any Python-valid date (years 1 to
# 9999) so a single dropped digit slipped through every layer. This
# validator rejects any year < 1900 or > 2100 on common parent-level
# date fields. No false positives — no legitimate Avientek doc has a
# year outside this range.
#
# Wired on `before_save` for Quotation / Sales Order / Sales Invoice /
# Purchase Order / Purchase Receipt / Purchase Invoice / Delivery
# Note / Payment Entry / Journal Entry via hooks.py.

_DATE_SANITY_MIN_YEAR = 1900
_DATE_SANITY_MAX_YEAR = 2100

# Date-shape fields that show up across the wired doctypes. Each
# doctype only has SOME of these; non-existent fields are skipped
# silently via `doc.get` returning None.
_DATE_SANITY_FIELDS = (
	"transaction_date",
	"delivery_date",
	"posting_date",
	"due_date",
	"schedule_date",
	"po_date",
	"bill_date",
	"reference_date",
	"cheque_date",
	"valid_till",
	# Avientek custom date fields we routinely touch:
	"custom_sales_order_confirmation_date",
)


def validate_date_sanity(doc, method=None, *args, **kwargs):
	"""Reject documents where any parent-level date field has a year
	outside the [_DATE_SANITY_MIN_YEAR, _DATE_SANITY_MAX_YEAR] range.

	Catches the dropped-digit class of typo (e.g. 0205 instead of 2025,
	0225 instead of 2025) that Frappe + Python datetime accept silently
	because year-205 IS a valid date in pure datetime terms.

	Idempotent — calling on a doc with all-valid dates is a no-op.
	Signature widened with *args/**kwargs for forward-compat with Frappe
	doc_event composer extras (see
	[[feedback-frappe-doc-hook-composer-3arg-shape]]).
	"""
	from frappe.utils import getdate

	bad = []
	for fn in _DATE_SANITY_FIELDS:
		val = doc.get(fn)
		if not val:
			continue
		try:
			d = getdate(val)
		except Exception:
			# Frappe will reject unparseable dates with its own error
			# before this hook fires. If we get here on something
			# unparseable, let Frappe handle it — don't pile on.
			continue
		if d is None:
			continue
		year = d.year
		if year < _DATE_SANITY_MIN_YEAR or year > _DATE_SANITY_MAX_YEAR:
			bad.append((fn, val, year))

	if not bad:
		return

	# Build a clear, actionable error. Include EVERY bad field at once
	# so the user fixes them in one save round-trip.
	lines = [
		frappe._("{0} = <b>{1}</b> (year {2}) is outside the valid range "
		         "<b>{3}–{4}</b>. Looks like a digit typo on the year — "
		         "please correct before saving.").format(
		           frappe.unscrub(fn), val, year,
		           _DATE_SANITY_MIN_YEAR, _DATE_SANITY_MAX_YEAR)
		for fn, val, year in bad
	]
	frappe.throw(
		"<br>".join(lines),
		title=frappe._("Invalid date — year out of range"),
	)


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
