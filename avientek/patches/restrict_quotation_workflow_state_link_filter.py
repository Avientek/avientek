"""Restrict the Quotation workflow_state / workflow_status link pickers
to states actually used by the V3 workflow (+ legacy V2 bridge names).

Rahul 2026-06-02: the 'Workflow State' filter dropdown on Quotation
list view showed all 39 Workflow State records — including 'Pending
Project Lead Approval', 'Pending Events Head Approval' and other
states from unrelated workflows. Users picked the wrong V2-similar
name ('Pending Level 2 Approval' instead of 'Pending L2 Approval')
because both were in the dropdown and the names are confusingly
close.

Fix: set `link_filters` on the two Quotation Custom Fields
(workflow_state — Frappe-injected; workflow_status — Avientek mirror)
to restrict the link picker to ONLY the V3 workflow's states. The
V3 seeder already includes the V2 bridge state names ('Pending Level
1 Approval', 'Pending Level 2 Approval') as legitimate transitions
for legacy stuck quotes, so they stay in the allowed list.

Idempotent. Re-running just rewrites the same JSON.
"""

import json
import frappe


# V3 workflow states (must match seed_quotation_approval_v3_workflow.py
# state list). Kept inline so this patch is self-contained.
#
# Sridhar ERP-TKT-9 + TKT-11 2026-06-05: replaced "Pending For Approval"
# with "Pending L1 Approval" and removed the V2 legacy bridge entries
# from the FILTER set (the V3 workflow still keeps the bridges as
# safety-net transitions, but they should not appear as user-facing
# filter options — they confused users into thinking there were
# duplicate states). The companion patch
# `clean_quotation_workflow_state_filter_dropdown` updates existing
# sites; this seeder controls fresh installs.
ALLOWED_STATES = [
	"Approved",
	"Approved for Update",
	"Cancellation L2 Pending",
	"Cancellation Requested",
	"Cancelled",
	"Draft",
	"Pending L1 Approval",
	"Pending L2 Approval",
	"Rejected",
	"Requested for update",
	"Sent for Revision",
	"Submitted",
]

FIELDS = ("Quotation-workflow_state", "Quotation-workflow_status")


def execute():
	link_filters = json.dumps([
		["Workflow State", "name", "in", ALLOWED_STATES]
	])

	for cf_name in FIELDS:
		if not frappe.db.exists("Custom Field", cf_name):
			print(f"[restrict_quotation_workflow_state_link_filter] skip — {cf_name} not present")
			continue
		current = frappe.db.get_value("Custom Field", cf_name, "link_filters")
		if current == link_filters:
			print(f"[restrict_quotation_workflow_state_link_filter] up-to-date: {cf_name}")
			continue
		frappe.db.set_value("Custom Field", cf_name, "link_filters", link_filters, update_modified=False)
		print(f"[restrict_quotation_workflow_state_link_filter] updated {cf_name}")

	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
