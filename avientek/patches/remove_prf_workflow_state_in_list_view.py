"""Delete the Property Setter that added `workflow_state` as a list
view column on Payment Request Form. The previous setter caused a
duplicate "Status" + "Workflow State" column in the PRF list view —
both render the same workflow_state badge, since Frappe v15's
auto-injected "Status" column already reflects workflow_state when a
workflow is attached.

Sammish 2026-05-16 (Jithin spotted on screenshot): keep only the
in_standard_filter Property Setter (filter sidebar usefulness); drop
the in_list_view one.

Idempotent. Safe to re-run.
"""
import frappe


TARGET = "Payment Request Form-workflow_state-in_list_view"


def execute():
	if frappe.db.exists("Property Setter", TARGET):
		frappe.delete_doc("Property Setter", TARGET, ignore_permissions=True, force=True)
		frappe.db.commit()
		print(f"[remove_prf_workflow_state_in_list_view] deleted {TARGET}")
	else:
		print(f"[remove_prf_workflow_state_in_list_view] already absent — no-op")
