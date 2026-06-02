"""Rename Payment Request Reference.outstanding_amount label to 'Net Amount'.

Sridhar 2026-06-02: aligned terminology with the Currency Totals
'Net Amount' header (commit a6df151). The per-row child-table column
header was still labelled 'Net Payment' (the ERPNext-standard label for
the outstanding_amount field). Property Setter overrides to 'Net Amount'
for consistency across the form.

No data change — purely a label override. Affects only the visible
column header in the PRF Payment References grid. Idempotent.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	make_property_setter(
		"Payment Request Reference",
		"outstanding_amount",
		"label",
		"Net Amount",
		"Data",
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Payment Request Reference")
	frappe.clear_cache(doctype="Payment Request Form")
	print("[relabel_prf_outstanding_amount_to_net_amount] outstanding_amount label -> 'Net Amount'")
