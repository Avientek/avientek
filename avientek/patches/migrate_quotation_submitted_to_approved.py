"""Migrate Quotations stuck in 'Submitted' state to 'Approved'.

Sridhar 2026-06-01: removed the Draft → Submitted → Approved two-step in
favour of a direct Draft → Approved transition for auto-OK quotes.
Existing quotes that were submitted under the old flow now sit in
'Submitted' state forever (the Submitted → Approve transition is gone
from the V3 seeder).

This patch routes all Quotations currently in 'Submitted' state to
'Approved', preserving docstatus=1, and posts an audit Comment on each
so the trail is visible. Updates both `workflow_state` and the mirror
`workflow_status` (filter typeahead) field in one SQL pass.
Idempotent.
"""

import frappe
from frappe.utils import now_datetime


def execute():
	names = frappe.db.sql_list(
		"SELECT name FROM `tabQuotation` WHERE workflow_state = 'Submitted'"
	)
	if not names:
		print("[migrate_quotation_submitted_to_approved] no stuck quotes")
		return

	frappe.db.sql(
		"""
		UPDATE `tabQuotation`
		SET workflow_state = 'Approved',
		    workflow_status = 'Approved'
		WHERE workflow_state = 'Submitted'
		"""
	)
	ts = now_datetime().strftime("%Y-%m-%d %H:%M")
	for n in names:
		try:
			frappe.get_doc({
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": "Quotation",
				"reference_name": n,
				"content": (
					f"<b>Workflow auto-migrated</b> Submitted → Approved at "
					f"{ts} (V3 seeder collapsed the two-step into a direct "
					f"Draft → Approved transition; Sridhar 2026-06-01)."
				),
			}).insert(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(
				message=f"Migration audit comment failed for {n}: {e}",
				title="migrate_quotation_submitted_to_approved",
			)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print(f"[migrate_quotation_submitted_to_approved] migrated {len(names)} quotes Submitted → Approved")
