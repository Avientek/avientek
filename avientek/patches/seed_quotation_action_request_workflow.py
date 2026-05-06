"""Seed the Quotation Action Request Approval workflow + Workflow State
records. Idempotent — runs from patches.txt and from after_migrate so
edits to the canonical spec below propagate every deploy.

Sridhar 2026-05-06 Phase 2.
"""
import frappe


WORKFLOW_NAME = "Quotation Action Request Approval"

def _resolved_roles():
    """Return the dict {l1_role, l2_role, creator_role} read from
    Avientek Settings (with module defaults). The seeder calls this
    every time it runs so renaming a role in Avientek Settings
    propagates on the next migrate."""
    from avientek.api.quotation_high_probability import _settings_roles
    return _settings_roles()


def _build_states_transitions():
    """Resolve states + transitions based on the live role config."""
    cfg = _resolved_roles()
    creator = cfg["creator_role"]
    l1 = cfg["l1_role"]
    l2 = cfg["l2_role"]

    # Frappe Workflow requires doc_status=2 only from doc_status=1.
    # Keep Rejected at doc_status=1 (terminal, request closed).
    states = [
        # (state, doc_status, style, allow_edit)
        ("Pending",     "0", "Warning",   creator),
        ("L1 Approved", "0", "Primary",   l1),
        ("L2 Approved", "1", "Success",   l2),
        ("Executed",    "1", "Success",   "System Manager"),
        ("Rejected",    "1", "Danger",    "System Manager"),
    ]
    transitions = [
        # (from, action, next, allowed_role, allow_self_approval)
        ("Pending",     "Approve L1", "L1 Approved", l1, 0),
        ("Pending",     "Reject",     "Rejected",    l1, 0),
        ("L1 Approved", "Approve L2", "L2 Approved", l2, 0),
        ("L1 Approved", "Reject",     "Rejected",    l2, 0),
    ]
    return states, transitions


def execute():
    return seed()


def seed():
    """Idempotent: resolve states+transitions from Avientek Settings,
    ensure each Workflow State + Workflow Action Master record exists,
    then ensure the Workflow doc has the right states + transitions.
    Sridhar 2026-05-06: roles are now Avientek-Settings-driven so a
    rename in the UI propagates on the next migrate."""
    states, transitions = _build_states_transitions()

    # 1a. Workflow State records.
    for state, _ds, style, _edit in states:
        if not frappe.db.exists("Workflow State", state):
            ws = frappe.new_doc("Workflow State")
            ws.workflow_state_name = state
            ws.style = style
            ws.insert(ignore_permissions=True)

    # 1b. Workflow Action Master records (Frappe validates Link).
    for _f, action, _n, _r, _s in transitions:
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
    for state, ds, style, edit in states:
        wf.append("states", {
            "state": state,
            "doc_status": ds,
            "allow_edit": edit,
            "style": style,
        })

    wf.set("transitions", [])
    for s, action, ns, role, self_app in transitions:
        # Skip transitions whose role doesn't exist on this site —
        # avoids LinkValidationError on a fresh deploy where
        # `Procurement L2` etc. haven't been created yet. Logged so
        # ops know what was skipped.
        if not frappe.db.exists("Role", role):
            print(f"[seed_quotation_action_request_workflow] "
                  f"WARN role {role!r} missing — skipping transition "
                  f"{s} -[{action}]-> {ns}")
            continue
        wf.append("transitions", {
            "state": s,
            "action": action,
            "next_state": ns,
            "allowed": role,
            "allow_self_approval": self_app,
        })

    if not wf.transitions:
        print(f"[seed_quotation_action_request_workflow] "
              f"no valid transitions — workflow not saved (configure "
              f"roles in Avientek Settings then re-run migrate)")
        return
    wf.is_active = 1
    wf.flags.ignore_permissions = True
    wf.save()
    frappe.db.commit()
    print(
        f"[seed_quotation_action_request_workflow] "
        f"workflow={WORKFLOW_NAME} states={len(states)} "
        f"transitions={len(wf.transitions)} active=1"
    )
