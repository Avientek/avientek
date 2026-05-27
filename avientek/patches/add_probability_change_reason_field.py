"""Add Quotation.probability_change_reason Custom Field.

Sridhar 2026-05-27 (Probability BRD): when an end-user lowers
probability on a submitted Quotation from ≥75% to <75%, the popup
captures a mandatory "Reason for Change" which is stored here and
shown as an audit Comment on the doc.

Stored alongside the existing `probabilities` field. Editable on
submit (allow_on_submit=1) since the whole point is post-submit
edits. Read-only in the UI — the JS popup sets it; user doesn't
type into it directly.

Idempotent.
"""
import frappe


FIELD = "Quotation-probability_change_reason"


def execute():
	if frappe.db.exists("Custom Field", FIELD):
		print(f"[add_probability_change_reason_field] {FIELD} exists — skipping")
		return

	cf = frappe.new_doc("Custom Field")
	cf.dt = "Quotation"
	cf.fieldname = "probability_change_reason"
	cf.label = "Probability Change Reason"
	cf.fieldtype = "Long Text"
	cf.read_only = 1
	cf.allow_on_submit = 1
	cf.insert_after = "probabilities"
	cf.description = (
		"Captured automatically when sales lowers probability from ≥75% to <75% "
		"on a submitted Quotation. Visible to approvers reviewing the change."
	)
	cf.insert(ignore_permissions=True)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	print(f"[add_probability_change_reason_field] Created {FIELD}")
