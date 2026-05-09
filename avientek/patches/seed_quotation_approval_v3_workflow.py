"""Seed `Quotation Approval Workflow Avientek (V3)` — the SO-style
Document Approval flow that replaces the Quotation Action Request
2-level approval (Rahul/Sridhar 2026-05-08).

Design mirrors the existing Sales Order `Sales Order Updated` workflow:
single approver, doc-level checkboxes (`custom_request_for_update`,
`custom_cancellation_check`) drive transitions, mandatory note fields
gate the save.

Idempotent. Runs from after_migrate every time so the role config from
Avientek Settings (`quote_approval_role`, default `CS`) propagates on
each migrate. Renaming the role in the UI takes effect on the next
migrate.

What it does:
  1. Resolve approver + creator roles from Avientek Settings.
  2. Deactivate every other Quotation workflow (Frappe enforces only
     one active workflow per doctype).
  3. Ensure all 9 Workflow State + 14 Workflow Action Master records
     exist (with the right colors).
  4. Build the Workflow record with the right states + transitions.
  5. Activate it.
"""
import frappe


WORKFLOW_NAME = "Quotation Approval Workflow Avientek (V3)"
DOCTYPE = "Quotation"


# (state, doc_status, color)
STATES = [
    ("Draft",                  "0", "Danger"),
    ("Submitted",              "1", "Primary"),
    ("Requested for update",   "1", "Warning"),
    ("Approved for Update",    "1", "Warning"),
    ("Pending For Approval",   "1", "Warning"),
    ("Approved",               "1", "Success"),
    ("Sent for Revision",      "1", "Warning"),
    ("Cancellation Requested", "1", "Danger"),
    ("Cancelled",              "2", "Danger"),
    # Sridhar 2026-05-10: bridge legacy V2 states so quotes that were
    # mid-V2-flow at deploy time (e.g. Pending Level 2 Approval) become
    # actionable in V3. Without these, Frappe shows NO transitions for
    # any quote whose workflow_state isn't in the active workflow's
    # State table — approver button silently hidden.
    ("Pending Level 1 Approval", "0", "Warning"),
    ("Pending Level 2 Approval", "0", "Warning"),
]


def _resolved_roles():
    from avientek.api.quotation_high_probability import _settings_roles
    return _settings_roles()


def _build_transitions(creator, approver):
    """Mirror the SO Sales Order Updated transition set, single-approver.

    Returns list of tuples:
      (state, action, next_state, allowed_role, allow_self_approval, condition)
    """
    return [
        # Standard submit
        ("Draft",                  "Submit",                "Submitted",              "All",     1, ""),

        # Once submitted, fast-forward to Approved (no approval gate at this point —
        # the gate kicks in only when probability >= 75 and user requests change).
        ("Submitted",              "Approve",               "Approved",               "All",     1, ""),

        # Document Approval: user ticks one of the checkboxes + saves
        ("Approved",               "Request for Update",    "Requested for update",   creator,   1, "doc.custom_request_for_update"),
        ("Approved",               "Request Cancellation",  "Cancellation Requested", creator,   1, "doc.custom_cancellation_check"),

        # Approver decides on the update request
        ("Requested for update",   "Approve",               "Approved for Update",    approver,  0, ""),
        ("Requested for update",   "Reject Update",         "Approved",               approver,  0, ""),
        # User can withdraw the request by un-ticking the checkbox + saving
        ("Requested for update",   "Cancel Request",        "Approved",               creator,   1, "not doc.custom_request_for_update"),

        # User edits in Approved for Update → sends back for approval
        ("Approved for Update",    "Send for Approval",     "Pending For Approval",   creator,   1, ""),

        # Approver decides on the revised quote
        ("Pending For Approval",   "Approve",               "Approved",               approver,  0, ""),
        ("Pending For Approval",   "Reject",                "Sent for Revision",      approver,  0, ""),

        # Sent for Revision — user can save freely (handled by validator state-allow)
        # then re-submit for approval
        ("Sent for Revision",      "Send for Approval",     "Pending For Approval",   creator,   1, ""),

        # Cancellation flow
        ("Cancellation Requested", "Approve Cancellation",  "Cancelled",              approver,  0, ""),
        ("Cancellation Requested", "Reject Cancellation",   "Approved",               approver,  0, ""),
        ("Cancellation Requested", "Cancel Request",        "Approved",               creator,   1, "not doc.custom_cancellation_check"),

        # Sridhar 2026-05-10: bridge transitions for legacy V2 states.
        # Quotes that were mid-V2-flow at the V3 deploy carry these
        # workflow_state values. Approver can flush them to V3
        # 'Approved' (= equivalent of L2-approved in V2) or 'Cancelled'
        # if no longer relevant. allow_self_approval=0 keeps the audit
        # rule (creator can't approve own quote).
        ("Pending Level 1 Approval", "Approve",              "Approved",               approver,  0, ""),
        ("Pending Level 1 Approval", "Reject",               "Cancelled",              approver,  0, ""),
        ("Pending Level 2 Approval", "Approve",              "Approved",               approver,  0, ""),
        ("Pending Level 2 Approval", "Reject",               "Cancelled",              approver,  0, ""),
    ]


def _deactivate_other_workflows():
    """Deactivate every other workflow on Quotation (Frappe allows only
    one active workflow per doctype). Skips V3 itself."""
    others = frappe.db.sql(
        """SELECT name FROM `tabWorkflow`
           WHERE document_type = %s AND is_active = 1 AND name != %s""",
        (DOCTYPE, WORKFLOW_NAME),
        as_dict=True,
    )
    for o in others:
        frappe.db.set_value("Workflow", o["name"], "is_active", 0,
                              update_modified=False)
        print(f"  deactivated prior workflow: {o['name']}")
    return [o["name"] for o in others]


def execute():
    return seed()


def seed():
    cfg = _resolved_roles()
    creator = cfg["creator_role"]
    approver = cfg["approver_role"]

    # 0. Ensure both required roles exist before we wire transitions.
    missing_roles = [r for r in (creator, approver) if not frappe.db.exists("Role", r)]
    if missing_roles:
        print(f"[seed_quotation_approval_v3_workflow] WARN missing roles "
              f"on this site: {missing_roles}. Workflow will be created "
              f"but transitions referencing them will be skipped.")

    # 1. Workflow State records
    for state, _ds, color in STATES:
        if not frappe.db.exists("Workflow State", state):
            ws = frappe.new_doc("Workflow State")
            ws.workflow_state_name = state
            ws.style = color
            ws.insert(ignore_permissions=True)

    # 2. Workflow Action Master records (Frappe validates Link)
    transitions = _build_transitions(creator, approver)
    for _f, action, _n, _r, _s, _c in transitions:
        if not frappe.db.exists("Workflow Action Master", action):
            wa = frappe.new_doc("Workflow Action Master")
            wa.workflow_action_name = action
            wa.insert(ignore_permissions=True)

    # 3. Deactivate any other active Quotation workflow.
    _deactivate_other_workflows()

    # 4. Build the Workflow itself.
    if frappe.db.exists("Workflow", WORKFLOW_NAME):
        wf = frappe.get_doc("Workflow", WORKFLOW_NAME)
    else:
        wf = frappe.new_doc("Workflow")
        wf.workflow_name = WORKFLOW_NAME
        wf.document_type = DOCTYPE
        wf.workflow_state_field = "workflow_state"
        wf.send_email_alert = 0
        wf.override_status = 0

    # States
    wf.set("states", [])
    for state, ds, color in STATES:
        wf.append("states", {
            "state": state,
            "doc_status": ds,
            "allow_edit": "All",
            "style": color,
        })

    # Transitions — skip any whose role doesn't exist on this site
    wf.set("transitions", [])
    skipped = 0
    for s, action, ns, role, self_app, cond in transitions:
        if role not in ("All",) and not frappe.db.exists("Role", role):
            print(f"[seed_quotation_approval_v3_workflow] WARN role {role!r} "
                  f"missing — skipping transition {s} -[{action}]-> {ns}")
            skipped += 1
            continue
        wf.append("transitions", {
            "state": s,
            "action": action,
            "next_state": ns,
            "allowed": role,
            "allow_self_approval": self_app,
            "condition": cond or "",
        })

    if not wf.transitions:
        print(f"[seed_quotation_approval_v3_workflow] no valid transitions — "
              f"workflow not saved (configure roles in Avientek Settings then re-migrate)")
        return

    wf.is_active = 1
    wf.flags.ignore_permissions = True
    wf.save()
    frappe.db.commit()

    print(
        f"[seed_quotation_approval_v3_workflow] "
        f"workflow={WORKFLOW_NAME} states={len(STATES)} "
        f"transitions={len(wf.transitions)} skipped={skipped} active=1 "
        f"approver={approver!r} creator={creator!r}"
    )
