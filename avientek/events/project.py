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


def set_created_by(doc, method=None):
    """Stamp the creating user on the read-only 'Created By' field (point 3).
    Runs on before_insert so it is set once and never overwritten."""
    if not doc.get("custom_created_by"):
        doc.custom_created_by = frappe.session.user


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
