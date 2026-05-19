"""
Role-aware Number Card counters for Quotation workspace cards.

Cancelled Quotations / Quotes Requested For Update on the Sales Team
workspace used to count globally (~811 cancelled for everyone), which
is noisy for a sales rep who only cares about their own pipeline.

Per Jithin 2026-05-18: regular users should see ONLY their own
quotations in these two cards; approvers (anyone whose role is in
Avientek Settings' approver tables, plus System Manager / Administrator)
should keep seeing the global count.

These functions are wired up by setting the matching Number Card
JSON to `type: "Custom"` and `method:
"avientek.api.quotation_cards.<fn>"`.
"""

import frappe

from avientek.api.quotation_high_probability import _settings_roles


def _user_can_see_all_quotations() -> bool:
    """An "approver" — anyone with a role in the L1 or L2 approver
    pools from Avientek Settings, plus System Manager / Administrator
    — should see the global count. Everyone else is scoped to their
    own documents.
    """
    if frappe.session.user == "Administrator":
        return True
    cfg = _settings_roles()
    approver_roles = set(cfg.get("approver_roles") or ()) | set(
        cfg.get("l2_approver_roles") or ()
    ) | {"System Manager", "Administrator"}
    user_roles = set(frappe.get_roles(frappe.session.user))
    return bool(approver_roles & user_roles)


def _count_by_state(workflow_state) -> dict:
    """Count Quotations in `workflow_state`, scoped to the current user
    unless they are an approver. `workflow_state` may be a single
    string OR a list/tuple of state names — list inputs become a
    SQL `IN (...)` match.

    Returns a dict shaped for Number Card type=Custom — `value` is
    the number, `route` makes the card clickable through to a
    filtered list view.
    """
    if isinstance(workflow_state, (list, tuple)):
        state_filter = ["in", list(workflow_state)]
    else:
        state_filter = workflow_state

    filters = {"workflow_state": state_filter}
    route_options = {"workflow_state": state_filter}
    if not _user_can_see_all_quotations():
        filters["owner"] = frappe.session.user
        route_options["owner"] = frappe.session.user
    value = frappe.db.count("Quotation", filters=filters)
    return {
        "value": value,
        "fieldtype": "Int",
        "route": ["List", "Quotation"],
        "route_options": route_options,
    }


@frappe.whitelist()
def count_cancelled_quotations(filters=None):
    return _count_by_state("Cancelled")


@frappe.whitelist()
def count_quotes_requested_for_update(filters=None):
    return _count_by_state("Requested for update")


@frappe.whitelist()
def count_cancellation_requests(filters=None):
    """Quotes pending cancellation approval — anything in
    'Cancellation Requested' or 'Cancellation L2 Pending'. Mirrors the
    'Quotes Requested for Update' card but for cancellation flow.
    Jithin/Rahul 2026-05-19."""
    return _count_by_state(["Cancellation Requested", "Cancellation L2 Pending"])
