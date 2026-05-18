"""Quotation workflow-state email notifications (Phase 2 of the
Dashboard & Notification BRD).

Triggers on workflow_state transitions:
  - → Pending For Approval     → notify L1 approver(s) routed by sales team
  - → Pending L2 Approval      → notify L2 approver(s) routed by sales team
  - → Approved / Submitted     → notify creator + sales team + prior approvers
  - → Rejected / Returned for update → notify creator

Routing per Jithin BRD examples A & B:
  - Quote has Sales Person on doc.sales_team[*].sales_person
  - Approver = user with the configured approver role AND
    (no User Permission on Sales Person, OR a UP that includes
    the quote's sales person)
  - If no approver matches, fall back to ALL users with the role
    (so the doc never silently goes un-routed)

Master switches in Avientek Settings → Notifications:
  - enable_quotation_notifications: kill-switch for ALL outbound mail
  - enable_workflow_state_notifications: opt-in for Phase 2 specifically
  - restrict_notifications_to_workflow_participants: tightens the
    Approved/Rejected recipient list to people who actually touched
    the doc (creator, sales team, action takers).

ToDo creation runs regardless of the email toggles — it's an in-app
notification that doesn't cost mail quota.
"""

import frappe
from frappe import _

from avientek.api.quotation_high_probability import (
    _settings_roles,
    _render_quotation_email,
)


def _sales_person_email(sp_name):
    """Resolve a Sales Person record to a user email via the standard
    chain: Sales Person → Employee → User. Returns "" if any link is
    missing."""
    if not sp_name:
        return ""
    employee = frappe.db.get_value("Sales Person", sp_name, "employee")
    if not employee:
        return ""
    user_id = frappe.db.get_value("Employee", employee, "user_id")
    if not user_id:
        return ""
    return frappe.db.get_value("User", user_id, "email") or user_id


_TEMPLATE_FOR_STATE = {
    "Pending For Approval": "Quotation Approval Required",
    "Pending L2 Approval": "Quotation Approval Required",
    "Approved": "Quotation Approved",
    "Rejected": "Quotation Rejected",
    "Requested for update": "Quotation Rejected",  # same template, "returned for revision" wording
}


# ─────────────────────────────────────────────────────────────────────
# Public hook
# ─────────────────────────────────────────────────────────────────────


def on_state_change(doc, method=None):
    """Dispatcher — fires from Quotation on_update / on_update_after_submit.
    Detects workflow_state transitions and routes to the right notifier.
    """
    if doc.doctype != "Quotation":
        return

    if not bool(frappe.db.get_single_value(
        "Avientek Settings", "enable_workflow_state_notifications"
    )):
        return

    new_state = (doc.workflow_state or "").strip()
    if not new_state:
        return

    before = getattr(doc, "_doc_before_save", None)
    old_state = (before.workflow_state or "").strip() if before else ""
    if old_state == new_state:
        return  # no transition

    try:
        if new_state in ("Pending For Approval",):
            _notify_approval_required(doc, stage="L1")
        elif new_state == "Pending L2 Approval":
            _notify_approval_required(doc, stage="L2")
        elif new_state == "Approved":
            _notify_state_resolution(doc, "Quotation Approved")
        elif new_state in ("Rejected", "Requested for update"):
            _notify_state_resolution(doc, "Quotation Rejected")
    except Exception:
        # A notification failure must never block a workflow save.
        frappe.log_error(
            title=f"quotation_notifications: transition {old_state!r} → {new_state!r} failed",
            message=frappe.get_traceback(),
        )


# ─────────────────────────────────────────────────────────────────────
# Notification senders
# ─────────────────────────────────────────────────────────────────────


def _notify_approval_required(doc, stage="L1"):
    cfg = _settings_roles()
    if stage == "L2":
        roles = cfg.get("l2_approver_roles") or cfg.get("approver_roles") or ()
    else:
        roles = cfg.get("approver_roles") or ()
    if not roles:
        return

    approvers = _resolve_approvers_for_quote(doc, roles)
    if not approvers:
        return

    # ToDo for each approver (in-app prompt + the assignment widget).
    description = _(
        "{stage} approval required: Quotation {name} — {party}, "
        "{currency} {grand_total:,.2f}"
    ).format(
        stage=stage,
        name=doc.name,
        party=(doc.party_name or doc.quotation_to or ""),
        currency=(doc.currency or ""),
        grand_total=(doc.grand_total or 0),
    )
    for user in approvers:
        _assign_todo(doc, user, description)

    if not bool(frappe.db.get_single_value(
        "Avientek Settings", "enable_quotation_notifications"
    )):
        return  # ToDo only, no email

    subject, message = _render_quotation_email("Quotation Approval Required", doc)
    if not subject:
        return  # template missing; silent fail-safe (seed patch should have run)
    frappe.sendmail(
        recipients=list(approvers),
        subject=subject,
        message=message,
        reference_doctype="Quotation",
        reference_name=doc.name,
        now=False,
    )


def _notify_state_resolution(doc, template_name):
    """Approved / Rejected — notify the creator + (optionally) other
    workflow participants. Always creates a ToDo for the creator so
    they see it in their dashboard."""
    creator = doc.owner

    if creator:
        action_desc = "approved" if template_name == "Quotation Approved" else "returned for revision"
        _assign_todo(
            doc, creator,
            _("Quotation {name} {action}").format(name=doc.name, action=action_desc),
        )

    if not bool(frappe.db.get_single_value(
        "Avientek Settings", "enable_quotation_notifications"
    )):
        return  # ToDo only, no email

    recipients = set()
    if creator:
        recipients.add(creator)
    # Avientek Quotation uses a single sales_person Custom Field;
    # legacy/standard `sales_team` child table is supported as fallback.
    sp_pool = []
    primary_sp = (doc.get("sales_person") or "").strip()
    if primary_sp:
        sp_pool.append(primary_sp)
    for row in (doc.get("sales_team") or []):
        sp = getattr(row, "sales_person", None)
        if sp and sp not in sp_pool:
            sp_pool.append(sp)
    for sp in sp_pool:
        email = _sales_person_email(sp)
        if email:
            recipients.add(email)

    # Optionally include prior workflow participants so approvers see
    # the resolution of a quote they touched.
    restrict = bool(frappe.db.get_single_value(
        "Avientek Settings", "restrict_notifications_to_workflow_participants"
    ))
    if restrict:
        actions = frappe.db.get_all(
            "Workflow Action",
            filters={"reference_doctype": "Quotation", "reference_name": doc.name},
            fields=["user", "completed_by"],
        )
        for a in actions:
            if a.get("user"):
                recipients.add(a["user"])
            if a.get("completed_by"):
                recipients.add(a["completed_by"])

    recipients.discard("Administrator")
    if not recipients:
        return

    subject, message = _render_quotation_email(template_name, doc)
    if not subject:
        return
    frappe.sendmail(
        recipients=list(recipients),
        subject=subject,
        message=message,
        reference_doctype="Quotation",
        reference_name=doc.name,
        now=False,
    )


# ─────────────────────────────────────────────────────────────────────
# Sales-team-aware approver resolution (BRD Example A / B)
# ─────────────────────────────────────────────────────────────────────


def _resolve_approvers_for_quote(doc, approver_roles):
    """For each Sales Person on the quote, find users holding any of
    `approver_roles` whose User Permissions allow them to see that
    Sales Person. Returns a set of user emails.

    BRD Example A: Quote by Jithin → Sridhar (the approver scoped to
    Jithin's team via User Permission) gets the email.

    BRD Example B: Quote by Midhun → the GM-CS user with a UP for
    Sales Person = Midhun gets the email.

    Fallback: if no sales person on the quote OR no approver matches
    any of the listed sales persons, blast all users with the role —
    we never want the doc to silently sit un-routed.
    """
    if not approver_roles:
        return set()
    role_tuple = tuple(approver_roles)

    candidates = frappe.db.sql(
        """SELECT DISTINCT u.name
           FROM `tabUser` u
           INNER JOIN `tabHas Role` hr
             ON hr.parent = u.name AND hr.parenttype = 'User'
           WHERE u.enabled = 1 AND hr.role IN %(roles)s
             AND u.name NOT IN ('Administrator', 'Guest')""",
        {"roles": role_tuple},
        as_dict=False,
    )
    candidate_users = [r[0] for r in candidates]
    if not candidate_users:
        return set()

    # Avientek Quotation has a single Custom Field `sales_person`
    # (Link). Fall through to the standard sales_team child table as
    # a secondary source if the Custom Field is blank but the table
    # has rows (defensive — supports both setups).
    sales_persons = []
    primary_sp = (doc.get("sales_person") or "").strip()
    if primary_sp:
        sales_persons.append(primary_sp)
    for r in (doc.get("sales_team") or []):
        sp = getattr(r, "sales_person", None)
        if sp and sp not in sales_persons:
            sales_persons.append(sp)

    if not sales_persons:
        # No sales person — can't route specifically. Broad blast.
        return set(candidate_users)

    matched = set()
    for user in candidate_users:
        has_any_sp_perm = bool(frappe.db.exists(
            "User Permission",
            {"user": user, "allow": "Sales Person"},
        ))
        if not has_any_sp_perm:
            # User has no Sales Person restriction → sees everyone → eligible.
            matched.add(user)
            continue
        # User has Sales Person UP — only include if at least one of
        # the quote's sales persons is in their allow list.
        for sp in sales_persons:
            if frappe.db.exists(
                "User Permission",
                {"user": user, "allow": "Sales Person", "for_value": sp},
            ):
                matched.add(user)
                break

    if matched:
        return matched
    # Fallback so the doc never goes un-routed.
    return set(candidate_users)


# ─────────────────────────────────────────────────────────────────────
# ToDo / assignment helper
# ─────────────────────────────────────────────────────────────────────


def _assign_todo(doc, user, description):
    """Create an assignment ToDo on the doc for `user`. Idempotent —
    skips if an open ToDo with the same user already exists on this
    doc (avoids spamming on every workflow save)."""
    if not user or user == "Administrator":
        return
    existing = frappe.db.exists(
        "ToDo",
        {
            "reference_type": "Quotation",
            "reference_name": doc.name,
            "allocated_to": user,
            "status": "Open",
        },
    )
    if existing:
        return
    try:
        from frappe.desk.form.assign_to import add as add_assign
        add_assign({
            "doctype": "Quotation",
            "name": doc.name,
            "assign_to": [user],
            "description": description,
            "notify": 0,  # we send our own templated email
        })
    except Exception:
        # ToDo creation failure shouldn't block the save.
        frappe.log_error(
            title="quotation_notifications: _assign_todo failed",
            message=frappe.get_traceback(),
        )
