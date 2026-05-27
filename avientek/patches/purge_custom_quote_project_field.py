"""Permanently delete `Quotation.custom_quote_project` Custom Field.

Sridhar 2026-05-27: this Custom Field keeps reappearing after live
updates per his report. Audit showed:
- module=None on the Custom Field row (not exported by any app)
- Not in any /custom/*.json fixture in our repo
- Not in fixtures hook

Source of re-creation is therefore external (likely someone keeps
re-adding via Customize Form UI, or a Frappe Cloud restore step).
This patch deletes the field once. The accompanying after_migrate
hook `purge_custom_quote_project_field` re-runs the same delete on
every migrate so it stays gone even if something keeps re-adding.

Idempotent — re-running is a no-op once deleted.

Left in scope: `Quotation.project` and `Quotation.project_name`
Custom Fields share names with ERPNext standard fields and could
break reports/print formats if removed. Sridhar confirmed only
`custom_quote_project` should be deleted.
"""

import frappe


FIELD = "Quotation-custom_quote_project"


def execute():
	if not frappe.db.exists("Custom Field", FIELD):
		print(f"[purge_custom_quote_project_field] {FIELD} not present — already clean")
		return

	frappe.delete_doc("Custom Field", FIELD, ignore_permissions=True, force=True)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print(f"[purge_custom_quote_project_field] Deleted {FIELD}")
