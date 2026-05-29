"""Add Custom Fields for Pending Probability Change request flow.

Sridhar 2026-05-29 (BRD-faithful interpretation): when sales requests
a probability downgrade from ≥75% to <75%, the BRD says:
  - field visually reverts to old high value
  - pending request captured behind the scenes
  - L2 approver (from quote_l2_approver_roles) approves/rejects
  - on approve: probabilities updates to new value
  - on reject: pending cleared, original value stays

Fields added:
  - pending_probability_value     Data, captures the requested new value
  - pending_probability_status    Select: ""/Pending/Approved/Rejected
  - pending_probability_reason    Long Text, the reason sales gave
  - pending_probability_requested_by   Link User
  - pending_probability_requested_at   Datetime

All hidden=1 (not for user editing), allow_on_submit=1 (set after submit).

Idempotent.
"""
import frappe


FIELDS = [
	{
		"fieldname": "pending_probability_value",
		"label": "Pending Probability Value",
		"fieldtype": "Data",
	},
	{
		"fieldname": "pending_probability_status",
		"label": "Pending Probability Status",
		"fieldtype": "Select",
		"options": "\nPending\nApproved\nRejected",
	},
	{
		"fieldname": "pending_probability_reason",
		"label": "Pending Probability Reason",
		"fieldtype": "Long Text",
	},
	{
		"fieldname": "pending_probability_requested_by",
		"label": "Pending Probability Requested By",
		"fieldtype": "Link",
		"options": "User",
	},
	{
		"fieldname": "pending_probability_requested_at",
		"label": "Pending Probability Requested At",
		"fieldtype": "Datetime",
	},
]


def execute():
	prev = "probability_change_reason"
	for spec in FIELDS:
		name = f"Quotation-{spec['fieldname']}"
		if frappe.db.exists("Custom Field", name):
			# Ensure hidden=1 + allow_on_submit=1 even on existing rows
			frappe.db.set_value("Custom Field", name, {
				"hidden": 1,
				"allow_on_submit": 1,
				"read_only": 1,
			}, update_modified=False)
			continue

		cf = frappe.new_doc("Custom Field")
		cf.dt = "Quotation"
		cf.fieldname = spec["fieldname"]
		cf.label = spec["label"]
		cf.fieldtype = spec["fieldtype"]
		if spec.get("options"):
			cf.options = spec["options"]
		cf.hidden = 1
		cf.read_only = 1
		cf.allow_on_submit = 1
		cf.insert_after = prev
		cf.insert(ignore_permissions=True)
		prev = spec["fieldname"]
		print(f"[add_pending_probability_fields] Created {name}")

	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
