"""Post-submit detection for ghost vouchers.

Sridhar 2026-06-03 — Project B Phase 1 lock-the-door.

For every submittable doctype we care about, after submit() succeeds,
verify the expected GL Entry / Stock Ledger Entry rows actually got
created. If they didn't, log a Ghost Voucher Alert row.

No email. No automatic retry. No throw. The submit is already done;
we're just monitoring whether the side effects happened. Sridhar
reviews /app/ghost-voucher-alert on demand.

Hooked via doc_events['<doctype>']['on_submit'] -> 'verify_ledger_created'.
"""
import frappe
from frappe.utils import now_datetime


# (doctype, needs_gl, needs_sle) — keep aligned with audit patch
LEDGER_REQUIREMENTS = {
	"Sales Invoice":    (True, False),
	"Purchase Invoice": (True, False),
	"Journal Entry":    (True, False),
	"Payment Entry":    (True, False),
	"Stock Entry":      (False, True),
	"Delivery Note":    (True, True),
	"Purchase Receipt": (True, True),
}


def verify_ledger_created(doc, method=None):
	"""Generic post-submit verifier — registered on each doctype above.

	If GL/SLE counts are 0 immediately after submit (within the same
	request), record a Ghost Voucher Alert. We DO NOT throw — the
	submit is committed; we're just observing.
	"""
	dt = doc.doctype
	requirements = LEDGER_REQUIREMENTS.get(dt)
	if not requirements:
		return

	needs_gl, needs_sle = requirements
	gl_cnt = (
		frappe.db.count("GL Entry", {
			"voucher_type": dt, "voucher_no": doc.name, "is_cancelled": 0,
		}) if needs_gl else None
	)
	sle_cnt = (
		frappe.db.count("Stock Ledger Entry", {
			"voucher_type": dt, "voucher_no": doc.name, "is_cancelled": 0,
		}) if needs_sle else None
	)

	missing_gl = needs_gl and (gl_cnt == 0)
	missing_sle = needs_sle and (sle_cnt == 0)

	if not (missing_gl or missing_sle):
		return  # everything fine, no alert needed

	# Defensive — Alert doctype must exist (created by bench migrate)
	if not frappe.db.exists("DocType", "Ghost Voucher Alert"):
		return

	# Skip if we already alerted for this voucher recently
	# (deduplicate — same alert keeps coming if user retries submit on a
	# doc that was cancelled-and-resubmitted)
	existing = frappe.db.exists("Ghost Voucher Alert", {
		"voucher_type": dt, "voucher_no": doc.name,
	})
	if existing:
		return

	try:
		alert = frappe.new_doc("Ghost Voucher Alert")
		alert.voucher_type = dt
		alert.voucher_no = doc.name
		alert.company = getattr(doc, "company", None)
		alert.detected_on = now_datetime()
		alert.missing_gl = int(bool(missing_gl))
		alert.missing_sle = int(bool(missing_sle))
		alert.user = frappe.session.user
		alert.remarks = (
			f"Post-submit verification: missing_gl={bool(missing_gl)} "
			f"(count={gl_cnt}) missing_sle={bool(missing_sle)} (count={sle_cnt})"
		)
		alert.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		# Never let the alert mechanism break the user's transaction
		frappe.log_error(frappe.get_traceback(), "ghost_voucher_detector.verify_ledger_created")
