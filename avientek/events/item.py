import frappe
from frappe import _
import json
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt, getdate, nowdate, cint, cstr
from erpnext.controllers.buying_controller import BuyingController
from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder
from erpnext.buying.utils import validate_for_items

# ── Default company settings for auto-populating Item Defaults & Tax Templates ──
# Sammish 2026-05-15:
#   - Added 3 missing entries (KSA, AETPLS, AG). The AVIENTEK TRADING LLC
#     absence caused PO/PR on that company to fall back to the first
#     cross-company template (UAE VAT 5% - A) → VAT computed at 0%
#     because the UAE template has no row for VAT 15% - KSA account.
#   - Added `tax_category` to the matching entries so the auto-fill
#     sets Tax Category alongside Item Tax Template. ERPNext picks the
#     Item Tax row matching the transaction's tax_category at sale/
#     purchase time, so categorising rows correctly enables the
#     "customer-tax-category-driven switch" behaviour the team uses.
COMPANY_DEFAULTS = [
	{
		"company": "Avientek FZCO",
		"income_account": "3-01-01-02 - SALES (VAT) - A",
		"tax_template": "UAE VAT 5% - A",
		"tax_category": "FREE ZONE",
	},
	{
		"company": "Avientek Electronics Trading L.L.C",
		"income_account": "3-01-01-02 - SALES (VAT) - AETL",
		"tax_template": "UAE VAT 5% - AETL",
		"tax_category": "MAIN LAND",
	},
	{
		"company": "Avientek Trading W.L.L",
		"income_account": "3-01-01-01 - SALES EXEMPT - ATW",
		"tax_template": None,
		"tax_category": None,
	},
	{
		"company": "AVIENTEK ELECTRONICS TRADING LIMITED",
		"income_account": "3-01-01-02 - SALES (VAT) - AK",
		"tax_template": "Kenya Tax - AK",
		"tax_category": None,
	},
	{
		"company": "Establishment al-Wasa'it For communications and information Technology",
		"income_account": "3-01-01-02 - SALES (VAT) - EWCIT",
		"tax_template": "KSA VAT 15% - EWCIT",
		"tax_category": "KSA -VAT",
	},
	{
		"company": "AVIENTEK TRADING LLC",
		"income_account": "3-01-01-02 - SALES (VAT) - KSA",
		"tax_template": "KSA VAT 15% - KSA",
		"tax_category": "KSA -VAT",
	},
	{
		"company": "Avientek Electronics Trading Private Limited",
		"income_account": "3-01-01-02 - SALES (VAT) - AETPLS",
		"tax_template": "Singapore Tax - AETPLS",
		"tax_category": None,
	},
	{
		"company": "Avientek Group",
		"income_account": "3-01-01-02 - SALES (VAT) - AG",
		"tax_template": "UAE VAT 5% - AG",
		"tax_category": "MAIN LAND",
	},
	{
		"company": "Avientek Electronics Trading PVT. LTD",
		"income_account": None,
		"tax_template": "GST 18% - AETPL",
		"tax_category": "Registered Regular",
	},
]


def auto_populate_defaults(doc, method=None):
	"""Before save: auto-add missing Item Defaults and Item Tax Templates
	for all configured companies, AND back-fill `tax_category` on any
	existing Item Tax row that matches a known template but has tax_category
	left blank.
	"""
	existing_companies = {d.company for d in doc.get("item_defaults", [])}
	# Index existing tax rows by template so we can both detect dups AND
	# back-fill missing tax_category on rows that already exist.
	tax_rows_by_template = {t.item_tax_template: t for t in doc.get("taxes", []) if t.item_tax_template}

	for entry in COMPANY_DEFAULTS:
		# Add Item Default row if company is missing
		if entry["company"] not in existing_companies:
			row = {"company": entry["company"]}
			if entry.get("income_account"):
				row["income_account"] = entry["income_account"]
			doc.append("item_defaults", row)

		# Add Item Tax row if template is missing
		tpl = entry.get("tax_template")
		if not tpl:
			continue
		cat = entry.get("tax_category")
		if tpl not in tax_rows_by_template:
			tax_row = {"item_tax_template": tpl}
			if cat:
				tax_row["tax_category"] = cat
			doc.append("taxes", tax_row)
		else:
			# Row already exists — back-fill tax_category if blank.
			existing = tax_rows_by_template[tpl]
			if cat and not getattr(existing, "tax_category", None):
				existing.tax_category = cat


def validate_brand_pn(doc,method):
	if frappe.db.exists("Item",{"brand": doc.brand,"part_number":doc.part_number,"name":['!=',doc.name]}):
		frappe.throw("There is already another item present with same brand and part number. Please review")


@frappe.whitelist()
def get_custom_duty(item=None,company=None):
	d = frappe.db.sql("""select tid.custom_duty from `tabItem Default` tid where '{0}'=tid.parent and tid.company ='{1}'""".format(item,company),
        as_dict=1)
	if d:
		return d[0].custom_duty
