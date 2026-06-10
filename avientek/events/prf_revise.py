"""Revise action handler for Payment Request Form (Sridhar 2026-05-27).

When an approver hits 'Revise' on an Authorised PRF, the workflow transitions
Authorised → Draft. This module:

1. Captures the mandatory reason (passed in by the JS popup) into
   PRF.revise_reason so the creator can see it on form load.
2. Posts an audit Comment on the PRF with reason + approver + timestamp.
3. Sends an email + ToDo to the original creator so they know to act on it.

The actual workflow transition itself is performed by Frappe's standard
apply_workflow — this module just decorates the transition with reason
capture, audit trail, and notifications.
"""
import frappe
from frappe import _
from frappe.utils import now_datetime


REVISE_ALLOWED_FROM_STATES = {"Authorised", "Rejected"}


def _apply_revise_side_effects(doc, reason: str, by_user: str | None = None):
	"""Run the three Revise side-effects on the PRF doc:

	    1. Persist `revise_reason` field (creator sees it on form load)
	    2. Add audit Comment with reason + approver + timestamp
	    3. Email + ToDo to the original creator

	Idempotency is enforced at the call site: callers check whether
	revise_reason is already set before invoking this (and skip if so).

	`by_user` defaults to `frappe.session.user` and identifies the
	approver who triggered the Revise transition.
	"""
	by_user = by_user or frappe.session.user

	# 1. Capture reason on the doc
	doc.db_set("revise_reason", reason, update_modified=False)

	# 2. Audit Comment
	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Info",
		"reference_doctype": "Payment Request Form",
		"reference_name": doc.name,
		"content": _(
			"<b>Sent for Revise</b> by {0} at {1}.<br><b>Reason:</b> {2}"
		).format(
			by_user,
			now_datetime().strftime("%Y-%m-%d %H:%M"),
			frappe.utils.escape_html(reason),
		),
	}).insert(ignore_permissions=True)

	# 3. Notify creator (email + ToDo).
	_notify_creator(doc, reason)


@frappe.whitelist()
def send_for_revise(prf_name: str, reason: str):
	"""Custom-dialog API entry. Called from the legacy JS popup BEFORE
	the workflow action is dispatched (when custom_enable_confirmation=0
	on the PRF workflow). Validates inputs + runs the shared side-effects.

	When custom_enable_confirmation=1 on the PRF workflow, the JS dialog
	auto-skips itself (see payment_request_form.js:before_workflow_action)
	and this endpoint is not called — `fill_revise_side_effects` (the
	on_update_after_submit hook below) covers the same side-effects
	after the generic confirmation dialog confirms the transition.

	Sridhar ERP-TKT-18 2026-06-05: REVISE_ALLOWED_FROM_STATES covers both
	Authorised and Rejected source states (matches the V3 PRF workflow
	seeder which exposes Rejected → Revise → Draft).
	"""
	if not prf_name:
		frappe.throw(_("PRF name is required."))
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Reason for revise is required."))

	doc = frappe.get_doc("Payment Request Form", prf_name)

	if doc.workflow_state not in REVISE_ALLOWED_FROM_STATES:
		frappe.throw(
			_("PRF must be in {0} to be sent for revision. Current state: {1}").format(
				" or ".join(sorted(REVISE_ALLOWED_FROM_STATES)), doc.workflow_state
			)
		)

	_apply_revise_side_effects(doc, reason)
	return {"ok": True}


def fill_revise_side_effects(doc, method=None):
	"""doc_events on_update_after_submit hook for Payment Request Form.

	Sridhar/Rahul 2026-06-10: when the PRF workflow has
	custom_enable_confirmation=1, the JS-side custom Revise dialog skips
	itself (payment_request_form.js:before_workflow_action) so the user
	only sees ONE dialog — the generic workflow_confirm.js one. Without
	this server-side fallback, the standard workflow transition would
	land with no revise_reason saved, no audit Comment, and no creator
	notification — a major regression vs the custom-dialog path.

	This hook detects the post-transition state of a Revise action and
	runs the same three side-effects `send_for_revise` does, pulling
	the reason from whatever the user typed in the generic dialog's
	"Remarks" textarea (logged into Workflow Action Log microseconds ago).

	Idempotent: skipped when revise_reason is already populated, which
	means the custom dialog already handled it via send_for_revise.
	"""
	# Cheap early-exit: only matters when the doc JUST transitioned to
	# Draft (the to_state for every Revise transition in the V3 PRF
	# workflow seeder).
	if getattr(doc, "workflow_state", None) != "Draft":
		return
	if getattr(doc, "revise_reason", None):
		# Custom dialog (send_for_revise) already ran. Don't double-notify.
		return

	# Find the most recent Workflow Action Log entry for Revise on this
	# PRF — the generic dialog logged it microseconds ago. Filter
	# action='Revise' so a subsequent action's remarks don't get picked
	# up. Whitelist from_state to avoid notifying for any unrelated
	# Draft transition (defence-in-depth).
	log = frappe.db.get_value(
		"Workflow Action Log",
		{
			"reference_doctype": "Payment Request Form",
			"reference_name": doc.name,
			"action": "Revise",
		},
		["remarks", "from_state", "owner"],
		order_by="creation desc",
		as_dict=True,
	)
	if not log:
		return
	if log.from_state not in REVISE_ALLOWED_FROM_STATES:
		return

	reason = (log.remarks or "").strip() or _("Sent back for revision (no remarks given).")
	_apply_revise_side_effects(doc, reason, by_user=log.owner)


def _notify_creator(doc, reason: str):
	"""Email + ToDo to the PRF creator about the revise request."""
	creator = doc.owner
	if not creator or creator == frappe.session.user:
		# Approver IS the creator (rare; self-approval scenarios) — skip.
		return

	# ToDo always created
	try:
		todo = frappe.get_doc({
			"doctype": "ToDo",
			"allocated_to": creator,
			"reference_type": "Payment Request Form",
			"reference_name": doc.name,
			"description": _(
				"PRF {0} sent back for revision by {1}. Reason: {2}"
			).format(doc.name, frappe.session.user, reason),
			"priority": "High",
			"status": "Open",
		})
		todo.insert(ignore_permissions=True)
	except Exception as e:
		frappe.log_error(
			message=f"PRF revise ToDo failed for {doc.name}: {e}",
			title="prf_revise ToDo",
		)

	# Email only if Avientek master switch ON
	try:
		settings = frappe.get_single("Avientek Settings")
		if not (settings.get("enable_workflow_state_notifications") or 0):
			return

		subject = _("PRF {0} sent back for revision").format(doc.name)
		message = _(
			"<p>Hi,</p>"
			"<p>Your Payment Request Form <b>{0}</b> has been sent back for revision "
			"by <b>{1}</b>.</p>"
			"<p><b>Reason:</b><br>{2}</p>"
			"<p>Please open the document, make the requested changes, and re-submit.</p>"
			"<p><a href=\"{3}/app/payment-request-form/{0}\">Open PRF</a></p>"
		).format(
			doc.name,
			frappe.session.user,
			frappe.utils.escape_html(reason).replace("\n", "<br>"),
			frappe.utils.get_url(),
		)
		frappe.sendmail(
			recipients=[creator],
			subject=subject,
			message=message,
			reference_doctype="Payment Request Form",
			reference_name=doc.name,
		)
	except Exception as e:
		frappe.log_error(
			message=f"PRF revise email failed for {doc.name}: {e}",
			title="prf_revise email",
		)
