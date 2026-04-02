import frappe
from frappe import _


# ── Server Script: "DN - Item Tax Template" ──
# DocType Event: Delivery Note, Before Validate
def validate_item_tax_template(doc, method=None):
    """Require Item Tax Template for all items when company is Avientek Electronics Trading PVT. LTD."""
    if doc.company == "Avientek Electronics Trading PVT. LTD":
        for item in doc.items:
            if not item.item_tax_template:
                frappe.throw(
                    _("Kindly choose Item Tax template for item: {0} in Row# {1}").format(
                        item.item_code, item.idx
                    )
                )
