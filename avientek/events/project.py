# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
"""
Project module enhancement (Rahul Prakash, 2026-08-22).

Adds a sales-pipeline layer to Project: a custom status
(custom_project_status) plus sales fields, and a Level-2 approval gate — once
a project is Approved, changing its status (to anything but Closed) or its
Expected Closing Date requires the "Project L2 Approver" role.

The custom fields themselves are created in migrate.py
(_create_project_enhancement_fields); this module holds the runtime rules.
"""
import frappe
from frappe import _

PROJECT_L2_ROLE = "Project L2 Approver"
_APPROVED = "Approved"

# Roles that see EVERY project regardless of the sales-person scope
# (Rahul follow-up 2026-08-25, item 6).
_PROJECT_VISIBILITY_BYPASS_ROLES = {"System Manager", "Projects Manager"}
# Only read-like access is scoped; creation / editing one's own project is
# unaffected (a user can't open a project that isn't in their list anyway).
_PROJECT_SCOPED_PTYPES = {"read", "select", "email", "print", "export", "report"}


def set_created_by(doc, method=None):
    """Stamp the creating user on the read-only 'Created By' field (point 3).
    Runs on before_insert so it is set once and never overwritten."""
    if not doc.get("custom_created_by"):
        doc.custom_created_by = frappe.session.user


def set_parent_sales_person(doc, method=None):
    """'Parent Sales Person' is a user-selectable field (ticket #0522) —
    independent of the Assigned Sales Person, and pickable even when no
    Assigned Sales Person is set. This hook only fills it as a CONVENIENCE:
    when the user leaves it blank AND an Assigned Sales Person is set, derive
    it from that SP's parent in the Sales Person tree. A value the user chose
    is never overwritten or cleared (that was the old read-only behaviour).
    Both feed the visibility rule (project_permission_query)."""
    if doc.get("custom_parent_sales_person"):
        return  # user (or a prior fill) set it — leave it alone
    assigned = doc.get("custom_sales_person")
    if assigned:
        doc.custom_parent_sales_person = frappe.db.get_value(
            "Sales Person", assigned, "parent_sales_person"
        )


# ── Item 6: project visibility by sales person / creator ──────────────
def _project_sales_persons(user):
    """Sales Persons this user is scoped to, via their Sales Person User
    Permissions (Sales Person has no user_id on this site). Empty list means
    the user has NO sales-person restriction → full visibility."""
    from avientek.api.user_permission_utils import get_user_permission_values
    return get_user_permission_values(user, "Sales Person")


def _project_visibility_bypass(user):
    if user == "Administrator":
        return True
    return bool(_PROJECT_VISIBILITY_BYPASS_ROLES & set(frappe.get_roles(user)))


def project_permission_query(user=None):
    """List-view scope (item 6): a restricted sales user sees a Project only
    when its Assigned Sales Person / Parent Sales Person / Project by is one of
    their permitted Sales Persons, OR they created it. Bypassed for Admin /
    System Manager / Projects Manager / users with no Sales Person restriction.
    """
    user = user or frappe.session.user
    if _project_visibility_bypass(user):
        return ""
    sps = _project_sales_persons(user)
    if not sps:
        return ""  # no Sales Person restriction → full visibility
    sp_list = ", ".join(frappe.db.escape(s) for s in sps)
    esc_user = frappe.db.escape(user)
    return (
        "(`tabProject`.`custom_sales_person` in ({sp})"
        " or `tabProject`.`custom_parent_sales_person` in ({sp})"
        " or `tabProject`.`custom_project_by` in ({sp})"
        " or `tabProject`.`custom_created_by` = {u})"
    ).format(sp=sp_list, u=esc_user)


def has_project_permission(doc, ptype=None, user=None):
    """Single-doc gate mirroring project_permission_query, for direct URL /
    link access. Only read-like ptypes are scoped; creation and other actions
    are left to the standard role permissions."""
    user = user or frappe.session.user
    if ptype and ptype not in _PROJECT_SCOPED_PTYPES:
        return True
    if _project_visibility_bypass(user):
        return True
    sps = set(_project_sales_persons(user))
    if not sps:
        return True
    if doc.get("custom_created_by") == user:
        return True
    for fn in ("custom_sales_person", "custom_parent_sales_person", "custom_project_by"):
        val = doc.get(fn)
        if val and val in sps:
            return True
    return False


def enforce_l2_approval(doc, method=None):
    """Points 8 & 11: once a Project reaches 'Approved' (custom_project_status),
    changing its status to anything other than 'Closed', or changing its
    Expected Closing Date, requires Level 2 approval — the user must hold the
    'Project L2 Approver' role. System Manager / Administrator bypass, the same
    way the other Avientek approval gates do.

    Only fires when the project WAS Approved before this save; a project being
    moved INTO Approved, or edited in any other state, is unaffected.
    """
    if doc.is_new():
        return
    before = doc.get_doc_before_save()
    if not before:
        return
    if (before.get("custom_project_status") or "") != _APPROVED:
        return

    user = frappe.session.user
    if user == "Administrator":
        return
    roles = set(frappe.get_roles(user))
    if "System Manager" in roles or PROJECT_L2_ROLE in roles:
        return

    new_status = doc.get("custom_project_status") or ""
    if new_status != _APPROVED and new_status != "Closed":
        frappe.throw(
            _("Changing an Approved project's status to <b>{0}</b> needs Level 2 "
              "approval (the <b>{1}</b> role).").format(new_status, PROJECT_L2_ROLE),
            title=_("Level 2 Approval Required"),
        )

    if (before.get("custom_expected_closing_date") or None) != (
        doc.get("custom_expected_closing_date") or None
    ):
        frappe.throw(
            _("Changing an Approved project's Expected Closing Date needs Level 2 "
              "approval (the <b>{0}</b> role).").format(PROJECT_L2_ROLE),
            title=_("Level 2 Approval Required"),
        )
