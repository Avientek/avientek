import frappe
from frappe import _
import json
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt, getdate, nowdate, cint, cstr
from erpnext.controllers.buying_controller import BuyingController
from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder
from erpnext.buying.utils import validate_for_items

def validate_brand_pn(doc,method):
	if frappe.db.exists("Item",{"brand": doc.brand,"part_number":doc.part_number,"name":['!=',doc.name]}):
		frappe.throw("There is already another item present with same brand and part number. Please review")


@frappe.whitelist()
def get_custom_duty(item=None,company=None):
	d = frappe.db.sql("""select tid.custom_duty from `tabItem Default` tid where '{0}'=tid.parent and tid.company ='{1}'""".format(item,company),
        as_dict=1)
	if d:
		return d[0].custom_duty
