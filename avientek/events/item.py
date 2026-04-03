import frappe
from frappe import _
import json
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt, getdate, nowdate, cint, cstr
from erpnext.controllers.buying_controller import BuyingController
from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder
from erpnext.buying.utils import validate_for_items

# ── Default company settings for auto-populating Item Defaults & Tax Templates ──
COMPANY_DEFAULTS = [
	{
		"company": "Avientek FZCO",
		"income_account": "3-01-01-02 - SALES (VAT) - A",
		"tax_template": "UAE VAT 5% - A",
	},
	{
		"company": "Avientek Electronics Trading L.L.C",
		"income_account": "3-01-01-02 - SALES (VAT) - AETL",
		"tax_template": "UAE VAT 5% - AETL",
	},
	{
		"company": "Avientek Trading W.L.L",
		"income_account": "3-01-01-01 - SALES EXEMPT - ATW",
		"tax_template": None,
	},
	{
		"company": "AVIENTEK ELECTRONICS TRADING LIMITED",
		"income_account": "3-01-01-02 - SALES (VAT) - AK",
		"tax_template": "Kenya Tax - AK",
	},
	{
		"company": "Establishment al-Wasa'it For communications and information Technology",
		"income_account": "3-01-01-02 - SALES (VAT) - EWCIT",
		"tax_template": "KSA VAT 15% - EWCIT",
	},
	{
		"company": "Avientek Electronics Trading PVT. LTD",
		"income_account": None,
		"tax_template": "GST 18% - AETPL",
	},
]


def auto_populate_defaults(doc, method=None):
	"""Before save: auto-add missing Item Defaults and Item Tax Templates for all companies."""
	existing_companies = {d.company for d in doc.get("item_defaults", [])}
	existing_templates = {t.item_tax_template for t in doc.get("taxes", [])}

	for entry in COMPANY_DEFAULTS:
		# Add Item Default row if company is missing
		if entry["company"] not in existing_companies:
			row = {"company": entry["company"]}
			if entry.get("income_account"):
				row["income_account"] = entry["income_account"]
			doc.append("item_defaults", row)

		# Add Item Tax row if template is missing
		if entry.get("tax_template") and entry["tax_template"] not in existing_templates:
			doc.append("taxes", {"item_tax_template": entry["tax_template"]})


def validate_brand_pn(doc,method):
	if frappe.db.exists("Item",{"brand": doc.brand,"part_number":doc.part_number,"name":['!=',doc.name]}):
		frappe.throw("There is already another item present with same brand and part number. Please review")


@frappe.whitelist()
def get_custom_duty(item=None,company=None):
	d = frappe.db.sql("""select tid.custom_duty from `tabItem Default` tid where '{0}'=tid.parent and tid.company ='{1}'""".format(item,company),
        as_dict=1)
	if d:
		return d[0].custom_duty
