"""Set Payment Request Form conversion_rate precision to 6.

Jithin 2026-06-02 (AVFZC-02215): the 'Exchange Rate' field on PRF
showed 3.67 when the stored system rate was 3.6725 — exchange rates
need at least 4 decimals to avoid round-trip drift on AED <-> foreign
currency. Standard Float precision on this DocField was NULL (system
default = 2). The sibling `transfer_exchange_rate` field is already
precision=6; align conversion_rate to match.

Idempotent Property Setter.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	make_property_setter(
		"Payment Request Form", "conversion_rate", "precision", "6", "Select",
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Payment Request Form")
	print("[set_prf_conversion_rate_precision_6] precision=6 applied")
