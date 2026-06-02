"""One-time backfill: sync workflow_status = workflow_state on all Quotations.

Sridhar/Rahul 2026-06-02: workflow_status mirror Custom Field went out of
sync over weeks of workflow transitions because fetch_from="workflow_state"
isn't a valid Frappe fetch path (needs a Link.targetfield chain like
"customer.tax_id"). Result: filter on workflow_status returned wrong rows
(e.g. filter "Pending For Approval" listed Approved quotes whose
workflow_status was stale at "Pending For Approval").

The companion sync hook in events/quotation.py:sync_workflow_status keeps
the two fields aligned going forward on every save / workflow transition.
This patch does the one-time backfill for ALL existing Quotations, including
docstatus=2 cancelled docs (REST blocks those — direct SQL doesn't).

Idempotent — only updates rows where the two fields differ.
"""

import frappe


def execute():
	updated = frappe.db.sql(
		"""
		UPDATE `tabQuotation`
		SET workflow_status = workflow_state
		WHERE workflow_state IS NOT NULL
		  AND (workflow_status IS NULL OR workflow_status != workflow_state)
		""",
	)
	rowcount = frappe.db.sql("SELECT ROW_COUNT()")[0][0]
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print(f"[sync_quotation_workflow_status_field] backfilled {rowcount} rows")
