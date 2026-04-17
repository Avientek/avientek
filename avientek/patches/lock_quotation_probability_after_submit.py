"""Lock `probability` and `probabilities` on Quotation after submit.

Per Finance Manager's requirement: once a Quotation is submitted for
approvals, users must not be able to edit the probability directly —
only via Cancel + Amend, so revisions leave an audit trail.

Flips `allow_on_submit = 0` on the two user-editable probability
Custom Fields. Leaves `workflow_state` and `gst_breakup_table` alone
(both are system-updated and must stay editable on submit).
"""

import frappe


def execute():
    fields = [
        "Quotation-probability",
        "Quotation-probabilities",
    ]
    for name in fields:
        if frappe.db.exists("Custom Field", name):
            current = frappe.db.get_value("Custom Field", name, "allow_on_submit")
            if current == 1:
                frappe.db.set_value(
                    "Custom Field", name, "allow_on_submit", 0,
                    update_modified=False,
                )
                print(f"[lock_quotation_probability_after_submit] {name} -> allow_on_submit=0")
            else:
                print(f"[lock_quotation_probability_after_submit] {name} already locked")
        else:
            print(f"[lock_quotation_probability_after_submit] {name} missing, skipping")

    frappe.db.commit()
    frappe.clear_cache(doctype="Quotation")
