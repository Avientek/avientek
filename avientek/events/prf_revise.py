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


@frappe.whitelist()
def send_for_revise(prf_name: str, reason: str):
	"""Decorate the Revise transition with reason + audit + notification.

	Called from the client-side popup BEFORE the workflow action is
	dispatched. Saves reason on the doc and writes the audit Comment.
	The JS then triggers the workflow transition itself.
	"""
	if not prf_name:
		frappe.throw(_("PRF name is required."))
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Reason for revise is required."))

	doc = frappe.get_doc("Payment Request Form", prf_name)

	# Sridhar ERP-TKT-18 2026-06-05: was hard-coded to "Authorised" only,
	# but the V3 workflow seeder (`create_payment_request_workflow.py`)
	# ALREADY exposes `Rejected → Revise → Draft` as a legal transition
	# (role=All). The customer wants Rejected docs to also use the same
	# reason-popup flow so the creator gets an explanatory ToDo + email
	# (matches the original Sridhar BRD from 2026-05-27, which only
	# covered Authorised at the time). Allow both — same downstream
	# logic (audit Comment + creator notification + workflow apply
	# transitions to Draft regardless of which source state). If new
	# source states are added to the workflow later they should also be
	# whitelisted here.
	REVISE_ALLOWED_STATES = {"Authorised", "Rejected"}
	if doc.workflow_state not in REVISE_ALLOWED_STATES:
		frappe.throw(
			_("PRF must be in {0} to be sent for revision. Current state: {1}").format(
				" or ".join(sorted(REVISE_ALLOWED_STATES)), doc.workflow_state
			)
		)

	# 1. Capture reason on the doc
	doc.db_set("revise_reason", reason, update_modified=False)

	# 2. Audit Comment
	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Info",
		"reference_doctype": "Payment Request Form",
		"reference_name": prf_name,
		"content": _(
			"<b>Sent for Revise</b> by {0} at {1}.<br><b>Reason:</b> {2}"
		).format(
			frappe.session.user,
			now_datetime().strftime("%Y-%m-%d %H:%M"),
			frappe.utils.escape_html(reason),
		),
	}).insert(ignore_permissions=True)

	# 3. Notify creator (email + ToDo). Use existing Avientek notification
	#    settings as a master switch — if workflow-state notifications are
	#    disabled we still create the ToDo but skip the email.
	_notify_creator(doc, reason)

	return {"ok": True}


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
