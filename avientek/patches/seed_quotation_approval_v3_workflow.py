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
    # Rahul 2026-05-14 BRD: high-prob revisions go through L1 -> L2
    # chain. After L1 approves "Pending For Approval" the doc moves
    # here for the L2 approver to make the final call. Same pattern
    # for Cancellation -> "Cancellation L2 Pending".
    ("Pending L2 Approval",    "1", "Warning"),
    ("Approved",               "1", "Success"),
    ("Sent for Revision",      "1", "Warning"),
    ("Cancellation Requested", "1", "Danger"),
    ("Cancellation L2 Pending","1", "Danger"),
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


def _build_transitions(creators, approvers, l2_approvers=None):
    """Mirror the SO Sales Order Updated transition set.

    Sammish 2026-05-13: multi-role variant. `creators`, `approvers`,
    `l2_approvers` are TUPLES of role names. Every transition whose
    allowed role is "creator", "l1_approver", or "l2_approver" is
    emitted ONCE PER ROLE in the respective list (Frappe's `allowed`
    column is single-Link, so multi-role semantics = multiple rows).
    Fixed-role transitions ("All") emit once unchanged.

    Rahul/Sammish 2026-05-14: restored Level 1 -> Level 2 approval
    chain per the BRD. `l2_approvers` is the L2 pool; if omitted/empty
    it falls back to `approvers` (single-stage equivalent).

    Returns list of tuples:
      (state, action, next_state, allowed_role, allow_self_approval, condition)
    """
    # Normalise scalars to tuples (back-compat with the old call style).
    if isinstance(creators, str):
        creators = (creators,)
    if isinstance(approvers, str):
        approvers = (approvers,)
    if isinstance(l2_approvers, str):
        l2_approvers = (l2_approvers,)
    if not l2_approvers:
        l2_approvers = approvers  # single-stage fallback

    CANCEL_COND = "(doc.probability or 0) < 75 and doc.probabilities not in ('75%', '80%', '85%', '90%', '95%', '100%')"

    # Each entry: (state, action, next_state, role_key_or_literal, self_approval, condition).
    # role_key_or_literal is either:
    #   - "creator"      -> expanded per `creators` list
    #   - "l1_approver"  -> expanded per `approvers` list (Level 1 pool)
    #   - "l2_approver"  -> expanded per `l2_approvers` list (Level 2 pool)
    #   - any literal role name like "All" -> used as-is
    # Jithin 2026-05-17 — margin gate. set_margin_flags
    # (events/quotation.py:1258) sets `custom_auto_approve_ok = 0` when
    # any brand's margin is below the per-brand threshold. The V2
    # workflow gated Submit on `doc.custom_auto_approve_ok == 1` and
    # the V3 initial seed dropped it, allowing QN-LTD-26-02011 (-1.52%
    # margin) to bypass approval on 2026-05-13. Restored here:
    #   - Draft → Submit fires only when margin is auto-approve OK
    #   - New "Send for Approval" routes low-margin quotes through L1
    #   - Submitted → Approve also enforces the same flag so a quote
    #     auto-submitted (margin OK) can fast-forward, but if the
    #     flag is later flipped to 0 the Approve button hides.
    # safe_eval here only needs `==` + attribute access — no flt/cint
    # so it works under WHITELISTED_SAFE_EVAL_GLOBALS.
    AUTO_OK = "doc.custom_auto_approve_ok == 1"
    NEEDS_APPROVAL = "doc.custom_auto_approve_ok == 0"

    template = [
        # Auto-approved (margin OK) — Draft fast-forwards to Submitted.
        ("Draft",                  "Submit",                "Submitted",              "All",         1, AUTO_OK),

        # Low-margin route — Draft must enter the L1 approval chain.
        ("Draft",                  "Send for Approval",     "Pending For Approval",   "All",         1, NEEDS_APPROVAL),

        # Once submitted (margin OK), fast-forward to Approved. If the
        # margin flag has since flipped to 0 (e.g., post-save recalc),
        # the Approve button hides and the user must request L1/L2.
        ("Submitted",              "Approve",               "Approved",               "All",         1, AUTO_OK),

        # Document Approval: user ticks one of the checkboxes + saves.
        # Rahul 2026-05-15 — same transitions must fire from `Submitted`
        # state too. High-prob quotes in Submitted (not yet auto-approved
        # to Approved) were stuck: the user ticked Cancellation Check
        # / Request for Update + saved, but the only action button on
        # the Submitted state was "Approve" — there was no way to route
        # the request to L1 without first manually approving. Mirror
        # transitions added below.
        ("Approved",               "Request for Update",    "Requested for update",   "creator",     1, "doc.custom_request_for_update"),
        ("Approved",               "Request Cancellation",  "Cancellation Requested", "creator",     1, "doc.custom_cancellation_check"),
        ("Submitted",              "Request for Update",    "Requested for update",   "creator",     1, "doc.custom_request_for_update"),
        ("Submitted",              "Request Cancellation",  "Cancellation Requested", "creator",     1, "doc.custom_cancellation_check"),

        # Direct Cancel for low-prob / std-margin quotes only. Quotes
        # at >=75% MUST go through the 2-step Request Cancellation ->
        # L1 -> L2 chain (audit requirement).
        # Frappe's workflow safe_eval (frappe/utils/safe_exec.py
        # WHITELISTED_SAFE_EVAL_GLOBALS) only exposes int/float/round —
        # no flt/cint/max/min, no string methods on attributes.
        ("Approved",               "Cancel",                "Cancelled",              "All",         1, CANCEL_COND),
        ("Submitted",              "Cancel",                "Cancelled",              "All",         1, CANCEL_COND),

        # L1 approver decides on the user's REQUEST FOR UPDATE — this
        # is just permission to edit, single-stage approval is enough
        # (no L2 chain at this gate, the BRD's L1->L2 is for the
        # actual amend submission below).
        ("Requested for update",   "Approve",               "Approved for Update",    "l1_approver", 0, ""),
        ("Requested for update",   "Reject Update",         "Approved",               "l1_approver", 0, ""),
        # User can withdraw the request by un-ticking the checkbox + saving
        ("Requested for update",   "Cancel Request",        "Approved",               "creator",     1, "not doc.custom_request_for_update"),

        # User edits in Approved for Update -> sends back for approval
        ("Approved for Update",    "Send for Approval",     "Pending For Approval",   "creator",     1, ""),

        # BRD 2026-05-14: Pending For Approval is the L1 stage of the
        # amend chain. L1 approves -> Pending L2 Approval. L2 approves
        # -> Approved. Either stage can Reject -> Sent for Revision.
        ("Pending For Approval",   "Approve Level 1",       "Pending L2 Approval",    "l1_approver", 0, ""),
        ("Pending For Approval",   "Reject",                "Sent for Revision",      "l1_approver", 0, ""),
        ("Pending L2 Approval",    "Approve Level 2",       "Approved",               "l2_approver", 0, ""),
        ("Pending L2 Approval",    "Reject",                "Sent for Revision",      "l2_approver", 0, ""),

        # Sent for Revision -- user can save freely (handled by validator state-allow)
        # then re-submit for approval (re-enters the L1 stage).
        ("Sent for Revision",      "Send for Approval",     "Pending For Approval",   "creator",     1, ""),

        # BRD 2026-05-14: Cancellation also goes through L1 -> L2.
        # Cancellation Requested -> L1 -> Cancellation L2 Pending -> L2 -> Cancelled.
        ("Cancellation Requested", "Approve Cancellation Level 1", "Cancellation L2 Pending", "l1_approver", 0, ""),
        ("Cancellation Requested", "Reject Cancellation",          "Approved",                 "l1_approver", 0, ""),
        ("Cancellation L2 Pending","Approve Cancellation Level 2", "Cancelled",                "l2_approver", 0, ""),
        ("Cancellation L2 Pending","Reject Cancellation",          "Approved",                 "l2_approver", 0, ""),
        # User can withdraw the cancellation request from Cancellation Requested only.
        ("Cancellation Requested", "Cancel Request",        "Approved",               "creator",     1, "not doc.custom_cancellation_check"),

        # Bridge transitions for legacy V2 orphan quotes (Sridhar
        # 2026-05-10). These keep the V2-era stuck quotes actionable —
        # L1 approver can flush them straight to "Approved" (skipping
        # L2 because they pre-date the new chain).
        ("Pending Level 1 Approval", "Approve",             "Approved",               "l1_approver", 0, ""),
        ("Pending Level 1 Approval", "Reject",              "Draft",                  "l1_approver", 0, ""),
        ("Pending Level 2 Approval", "Approve",             "Approved",               "l1_approver", 0, ""),
        ("Pending Level 2 Approval", "Reject",              "Draft",                  "l1_approver", 0, ""),
    ]

    expanded = []
    seen = set()  # dedupe within the resulting list — if pools share a role
    for state, action, next_state, role_key, self_app, cond in template:
        if role_key == "creator":
            roles = creators
        elif role_key == "l1_approver":
            roles = approvers
        elif role_key == "l2_approver":
            roles = l2_approvers
        else:
            roles = (role_key,)
        for role in roles:
            key = (state, action, next_state, role)
            if key in seen:
                continue
            seen.add(key)
            expanded.append((state, action, next_state, role, self_app, cond))
    return expanded


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
    creators = cfg.get("creator_roles") or (cfg["creator_role"],)
    approvers = cfg.get("approver_roles") or (cfg["approver_role"],)
    l2_approvers = cfg.get("l2_approver_roles") or approvers

    # 0. Ensure required roles exist before we wire transitions.
    all_roles = set(creators) | set(approvers) | set(l2_approvers)
    missing_roles = sorted(r for r in all_roles if not frappe.db.exists("Role", r))
    if missing_roles:
        print(f"[seed_quotation_approval_v3_workflow] WARN missing roles "
              f"on this site: {missing_roles}. Workflow will be created "
              f"but transitions referencing them will fall back to "
              f"System Manager or be skipped.")

    # 1. Workflow State records
    for state, _ds, color in STATES:
        if not frappe.db.exists("Workflow State", state):
            ws = frappe.new_doc("Workflow State")
            ws.workflow_state_name = state
            ws.style = color
            ws.insert(ignore_permissions=True)

    # 2. Workflow Action Master records (Frappe validates Link)
    transitions = _build_transitions(creators, approvers, l2_approvers)
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

    # Transitions — fallback to System Manager if the configured role
    # is missing, so we never silently drop transitions (Sridhar
    # 2026-05-10: orders.mea couldn't approve because the bridge had
    # been silently skipped when GM role was misconfigured).
    wf.set("transitions", [])
    skipped = 0
    fallbacks = 0
    for s, action, ns, role, self_app, cond in transitions:
        actual_role = role
        if role not in ("All",) and not frappe.db.exists("Role", role):
            if frappe.db.exists("Role", "System Manager"):
                actual_role = "System Manager"
                fallbacks += 1
                print(f"[seed_quotation_approval_v3_workflow] WARN role "
                      f"{role!r} missing — falling back to System Manager "
                      f"for {s} -[{action}]-> {ns}")
            else:
                print(f"[seed_quotation_approval_v3_workflow] WARN role "
                      f"{role!r} missing AND System Manager missing — "
                      f"skipping {s} -[{action}]-> {ns}")
                skipped += 1
                continue
        wf.append("transitions", {
            "state": s,
            "action": action,
            "next_state": ns,
            "allowed": actual_role,
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
        f"L1={list(approvers)!r} L2={list(l2_approvers)!r} "
        f"creators={list(creators)!r}"
    )
