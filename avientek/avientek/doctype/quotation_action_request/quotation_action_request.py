"""Quotation Action Request — Phase 2 of Sridhar 2026-05-06 spec.

Wraps a request to Cancel / Amend / Resubmit a high-probability
Quotation in a 2-level approval workflow. Once the workflow reaches
the `Executed` state (after L2 approval), the doc executes the
underlying action programmatically.

Workflow states (defined in fixtures/workflow.json — Quotation Action
Request Approval):
  Pending           -- requester just submitted (default)
  L1 Approved       -- after Finance Manager approves
  L2 Approved       -- after Director approves; on_update fires the
                       underlying action and flips state to Executed.
  Executed          -- terminal happy path
  Rejected          -- terminal rejection
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


_TERMINAL_STATES = ("Executed", "Rejected")


class QuotationActionRequest(Document):
    def validate(self):
        if not self.workflow_state:
            self.workflow_state = "Pending"
        # Block creating a second open request for the same quote/action.
        if self.is_new():
            existing = frappe.db.exists(
                "Quotation Action Request",
                {
                    "quotation": self.quotation,
                    "action": self.action,
                    "workflow_state": ["not in", _TERMINAL_STATES],
                    "name": ["!=", self.name or ""],
                },
            )
            if existing:
                frappe.throw(
                    _("An open Action Request already exists for "
                      "Quotation {0} action {1}: {2}").format(
                        self.quotation, self.action, existing,
                    ),
                    title=_("Duplicate Action Request"),
                )
        # Verify the underlying quote is still in a state where the
        # requested action makes sense.
        q = frappe.db.get_value(
            "Quotation", self.quotation,
            ["docstatus", "workflow_state", "probability"],
            as_dict=True,
        )
        if not q:
            frappe.throw(_("Quotation {0} not found").format(self.quotation))
        if self.action == "Cancel" and q.docstatus != 1:
            frappe.throw(
                _("Cannot Cancel: Quotation {0} is not submitted "
                  "(docstatus={1}).").format(self.quotation, q.docstatus),
            )
        if self.action == "Amend" and q.docstatus not in (1, 2):
            frappe.throw(
                _("Cannot Amend: Quotation {0} is in draft (docstatus={1}). "
                  "Edit the draft directly.").format(
                    self.quotation, q.docstatus,
                ),
            )

    def on_update(self):
        """When the workflow reaches L2 Approved, fire the action and
        flip to Executed. on_update fires after every save, including
        the workflow state transition save — so we guard with
        `executed_on` to make this idempotent."""
        if self.workflow_state == "L1 Approved" and not self.level_1_approved_on:
            self.db_set("level_1_approver", frappe.session.user,
                         update_modified=False)
            self.db_set("level_1_approved_on", now_datetime(),
                         update_modified=False)
        if self.workflow_state == "L2 Approved" and not self.executed_on:
            self.db_set("level_2_approver", frappe.session.user,
                         update_modified=False)
            self.db_set("level_2_approved_on", now_datetime(),
                         update_modified=False)
            self._execute()

    # ── execution dispatch ─────────────────────────────────────────
    def _execute(self):
        # SAVEPOINT lets us rollback the action's partial DB writes if
        # it fails midway (e.g. doc.cancel() runs the DB write before
        # post-save link checks throw, leaving docstatus=2 stuck).
        savepoint = "qar_execute"
        try:
            frappe.db.savepoint(savepoint)
            if self.action == "Cancel":
                log = self._do_cancel()
            elif self.action == "Amend":
                log = self._do_amend()
            elif self.action == "Resubmit":
                log = self._do_resubmit()
            else:
                log = f"Unknown action {self.action!r} — no-op"
            self.db_set("execution_log", log, update_modified=False)
            self.db_set("executed_on", now_datetime(), update_modified=False)
            self.db_set("workflow_state", "Executed", update_modified=False)
            frappe.db.commit()
        except Exception as exc:
            # Roll the action's DB writes back so we don't leave the
            # quote half-cancelled / partially amended.
            try:
                frappe.db.rollback(save_point=savepoint)
            except Exception:
                pass
            self.db_set(
                "execution_log",
                f"Execution failed: {exc!r}\n\n{frappe.get_traceback()[:2000]}",
                update_modified=False,
            )
            frappe.db.commit()
            # Don't re-raise — leave the request in L2 Approved with
            # execution_log populated so an admin can retry. They can
            # set executed_on='' to retrigger via the manual button.
            frappe.log_error(
                title=f"QuotationActionRequest._execute failed for {self.name}",
                message=frappe.get_traceback(),
            )

    def _do_cancel(self):
        from avientek.api.quotation_high_probability import (
            _CONTEXT_BYPASS_FLAG,
        )
        # Bypass the high-prob doc_event guard — we ARE the approval
        # path that authorises this cancel.
        frappe.flags[_CONTEXT_BYPASS_FLAG] = True
        try:
            doc = frappe.get_doc("Quotation", self.quotation)
            if doc.docstatus != 1:
                return f"skipped: docstatus={doc.docstatus} (already cancelled?)"
            doc.cancel()
            return f"Cancelled Quotation {self.quotation} via Action Request {self.name}"
        finally:
            frappe.flags.pop(_CONTEXT_BYPASS_FLAG, None)

    def _do_amend(self):
        from avientek.api.quotation_high_probability import (
            _CONTEXT_BYPASS_FLAG,
        )
        frappe.flags[_CONTEXT_BYPASS_FLAG] = True
        try:
            doc = frappe.get_doc("Quotation", self.quotation)
            # Cancel first if still submitted (Frappe's amend creates a
            # new draft from a cancelled doc).
            if doc.docstatus == 1:
                doc.cancel()
                # Re-fetch after cancel; it's now docstatus=2.
                doc = frappe.get_doc("Quotation", self.quotation)
            if doc.docstatus != 2:
                return (f"skipped: docstatus={doc.docstatus} — "
                        f"can't amend without cancellation first")
            new_doc = frappe.copy_doc(doc, ignore_no_copy=False)
            new_doc.amended_from = self.quotation
            new_doc.docstatus = 0
            new_doc.insert(ignore_permissions=True)
            self.db_set("amended_quotation", new_doc.name,
                         update_modified=False)
            return (f"Amended Quotation {self.quotation} -> "
                    f"new draft {new_doc.name}")
        finally:
            frappe.flags.pop(_CONTEXT_BYPASS_FLAG, None)

    def _do_resubmit(self):
        from avientek.api.quotation_high_probability import (
            _CONTEXT_BYPASS_FLAG,
        )
        # Frappe doesn't have a native "resubmit" — pattern is cancel +
        # amend (duplicate to draft) + submit. We do cancel + amend; the
        # user re-submits the new draft from the form. This Action
        # Request leaves the new draft for them.
        frappe.flags[_CONTEXT_BYPASS_FLAG] = True
        try:
            log = []
            doc = frappe.get_doc("Quotation", self.quotation)
            if doc.docstatus == 1:
                doc.cancel()
                log.append(f"cancelled {self.quotation}")
                doc = frappe.get_doc("Quotation", self.quotation)
            if doc.docstatus == 2:
                new_doc = frappe.copy_doc(doc, ignore_no_copy=False)
                new_doc.amended_from = self.quotation
                new_doc.docstatus = 0
                new_doc.insert(ignore_permissions=True)
                self.db_set("amended_quotation", new_doc.name,
                             update_modified=False)
                log.append(f"amended -> {new_doc.name}")
                return " | ".join(log) + ". Submit the new draft from the form."
            return " | ".join(log) + f" (docstatus={doc.docstatus})"
        finally:
            frappe.flags.pop(_CONTEXT_BYPASS_FLAG, None)


@frappe.whitelist()
def has_open_request(quotation, action):
    """Return the name of an open Quotation Action Request for the
    given (quotation, action), or None if none exists. Used by the
    Quotation form JS to decide whether to show the "Open Existing
    Request" button or the "New Request" one."""
    return frappe.db.exists(
        "Quotation Action Request",
        {
            "quotation": quotation,
            "action": action,
            "workflow_state": ["not in", _TERMINAL_STATES],
        },
    )
