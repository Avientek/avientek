"""Neutralize mandatory_depends_on on Item.gst_hsn_code — keep it blank.

Sridhar 2026-07-09, round 2: this patch originally just DELETED the
Item-gst_hsn_code-mandatory_depends_on Property Setter (added
2026-07-08), assuming that would restore default (non-mandatory)
behavior. It didn't — deleting the override exposed the *original*
broken value baked directly onto the is_system_generated Custom Field
record itself (shipped by ERPNext's GST/HSN setup): the same dead
"gst_settings.validate_hsn_code && doc.is_sales_item" expression that
caused the original "Invalid depends_on expression" crash this whole
saga started with. The 2026-07-08 Property Setter was MASKING that
broken value with a working one (eval:doc.is_sales_item), not fixing
it at the source — deleting the mask re-exposed the original bug.

Fix: keep a Property Setter in place, but with an explicit BLANK value,
so mandatory_depends_on always evaluates to nothing (never mandatory)
regardless of what the underlying Custom Field says. HSN/SAC
mandatory-ness is now a soft reminder instead
(avientek.events.item.warn_missing_hsn_for_sales_item, validate hook),
not a hard field rule — so blanking, not deleting, is the correct
permanent state here.

Idempotent — safe to re-run.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


PROPERTY_SETTER = "Item-gst_hsn_code-mandatory_depends_on"


def execute():
	existing = frappe.db.get_value("Property Setter", PROPERTY_SETTER, "value")

	if existing == "":
		print(f"[remove_hsn_mandatory_depends_on] {PROPERTY_SETTER} already blank — nothing to do")
		return

	if frappe.db.exists("Property Setter", PROPERTY_SETTER):
		frappe.db.set_value("Property Setter", PROPERTY_SETTER, "value", "")
	else:
		make_property_setter(
			"Item", "gst_hsn_code", "mandatory_depends_on", "", "Code", for_doctype=False,
		)

	frappe.db.commit()
	frappe.clear_cache(doctype="Item")
	print(f"[remove_hsn_mandatory_depends_on] {PROPERTY_SETTER} set to blank")
