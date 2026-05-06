"""Seed the Quotation Action Request Approval workflow + Workflow State
records. Idempotent — runs from patches.txt and from after_migrate so
edits to the canonical spec below propagate every deploy.

Sridhar 2026-05-06 Phase 2.
"""
import frappe


WORKFLOW_NAME = "Quotation Action Request Approval"

STATES = [
    # (state, doc_status, style, allow_edit)
    # Frappe Workflow requires a state transitioning to doc_status=2
    # (cancelled) be reachable only from doc_status=1. Rejected is a
    # terminal "request closed, denied" state — keep it at doc_status=1
    # rather than 2 so we can reach it from Pending or L1 Approved
    # (both doc_status=0). Same for Executed.
    ("Pending",     "0", "Warning",   "Sales User"),
    ("L1 Approved", "0", "Primary",   "Finance Manager"),
    ("L2 Approved", "1", "Success",   "Director"),
    ("Executed",    "1", "Success",   "System Manager"),
    ("Rejected",    "1", "Danger",    "System Manager"),
]

TRANSITIONS = [
    # (from, action, next, allowed_role, allow_self_approval)
    ("Pending",     "Approve L1", "L1 Approved", "Finance Manager", 0),
    ("Pending",     "Reject",     "Rejected",    "Finance Manager", 0),
    ("L1 Approved", "Approve L2", "L2 Approved", "Director",        0),
    ("L1 Approved", "Reject",     "Rejected",    "Director",        0),
]


def execute():
    return seed()


def seed():
    """Idempotent: ensure each Workflow State + Workflow Action Master
    record exists, then ensure the Workflow doc has the right states +
    transitions."""
    # 1a. Workflow State records.
    for state, _ds, style, _edit in STATES:
        if not frappe.db.exists("Workflow State", state):
            ws = frappe.new_doc("Workflow State")
            ws.workflow_state_name = state
            ws.style = style
            ws.insert(ignore_permissions=True)

    # 1b. Workflow Action Master records (Frappe validates Link).
    for _f, action, _n, _r, _s in TRANSITIONS:
        if not frappe.db.exists("Workflow Action Master", action):
            wa = frappe.new_doc("Workflow Action Master")
            wa.workflow_action_name = action
            wa.insert(ignore_permissions=True)

    # 2. The Workflow itself.
    if frappe.db.exists("Workflow", WORKFLOW_NAME):
        wf = frappe.get_doc("Workflow", WORKFLOW_NAME)
    else:
        wf = frappe.new_doc("Workflow")
        wf.workflow_name = WORKFLOW_NAME
        wf.document_type = "Quotation Action Request"
        wf.workflow_state_field = "workflow_state"
        wf.is_active = 1
        wf.send_email_alert = 0
        wf.override_status = 0

    wf.set("states", [])
    for state, ds, style, edit in STATES:
        wf.append("states", {
            "state": state,
            "doc_status": ds,
            "allow_edit": edit,
            "style": style,
        })

    wf.set("transitions", [])
    for s, action, ns, role, self_app in TRANSITIONS:
        wf.append("transitions", {
            "state": s,
            "action": action,
            "next_state": ns,
            "allowed": role,
            "allow_self_approval": self_app,
        })

    wf.is_active = 1
    wf.flags.ignore_permissions = True
    wf.save()
    frappe.db.commit()
    print(
        f"[seed_quotation_action_request_workflow] "
        f"workflow={WORKFLOW_NAME} states={len(STATES)} "
        f"transitions={len(TRANSITIONS)} active=1"
    )
