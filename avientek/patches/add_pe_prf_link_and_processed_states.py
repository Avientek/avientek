# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Jithin 2026-05-17 — two-part schema bump for the Released → Processed
# tracking feature:
#
#   1. Custom Field `payment_request_form` (Link → Payment Request Form)
#      on Payment Entry. Set programmatically by the
#      `create_payment_entry` mapper AND by the new "Get Payment Request
#      Form" picker on Payment Entry. Read-only in UI — users link via
#      the picker, not by typing.
#
#   2. Two new states on the PRF workflow: `Partially Processed` (style
#      Warning) and `Processed` (style Success). Both stay at
#      doc_status=1. The states are set programmatically by
#      avientek.events.payment_entry.update_prf_status_on_pe_submit
#      after every PE submit — no Workflow transitions are added (the
#      programmatic path bypasses Frappe's workflow action UI).
#
# Idempotent.

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


PRF_STATES_TO_ADD = [
    {"state": "Partially Processed", "doc_status": "1", "style": "Warning",
     "allow_edit": "System Manager"},
    {"state": "Processed", "doc_status": "1", "style": "Success",
     "allow_edit": "System Manager"},
]


def execute():
    _ensure_custom_field()
    _ensure_workflow_states()
    frappe.db.commit()


def _ensure_custom_field():
    if frappe.db.exists(
        "Custom Field",
        {"dt": "Payment Entry", "fieldname": "payment_request_form"},
    ):
        return

    # Insert after `reference_no` which sits in the section break used
    # for upstream document references. Falls back to end of doctype if
    # the anchor field doesn't exist on this Frappe version.
    insert_after = "reference_no"
    if not frappe.db.exists("DocField", {"parent": "Payment Entry", "fieldname": insert_after}):
        insert_after = None

    create_custom_field(
        "Payment Entry",
        {
            "fieldname": "payment_request_form",
            "label": "Payment Request Form",
            "fieldtype": "Link",
            "options": "Payment Request Form",
            "insert_after": insert_after,
            "read_only": 1,
            "no_copy": 1,
            "print_hide": 1,
            "description": "Set automatically by the 'Get Payment Request Form' picker or by Create → Payment Entry from a PRF. Drives the PRF's Processed / Partially Processed status.",
        },
    )


def _ensure_workflow_states():
    # Workflow States is a master doctype — Frappe Link-validates each
    # row in Workflow.states against it, so we have to create the master
    # records BEFORE appending to the workflow.
    for st in PRF_STATES_TO_ADD:
        if not frappe.db.exists("Workflow State", st["state"]):
            ws = frappe.new_doc("Workflow State")
            ws.workflow_state_name = st["state"]
            ws.style = st["style"]
            ws.insert(ignore_permissions=True)

    wf_name = frappe.db.get_value(
        "Workflow", {"document_type": "Payment Request Form", "is_active": 1}, "name"
    )
    if not wf_name:
        wf_name = frappe.db.get_value(
            "Workflow", {"document_type": "Payment Request Form"}, "name"
        )
    if not wf_name:
        print("add_pe_prf_link_and_processed_states: no PRF workflow found; skipping state add")
        return

    wf = frappe.get_doc("Workflow", wf_name)
    existing = {s.state for s in (wf.states or [])}
    changed = False
    for st in PRF_STATES_TO_ADD:
        if st["state"] in existing:
            continue
        wf.append("states", st)
        changed = True

    if changed:
        wf.save(ignore_permissions=True)
        print(f"add_pe_prf_link_and_processed_states: added Partially Processed / Processed to '{wf_name}'")
