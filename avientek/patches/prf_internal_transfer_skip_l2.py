"""Internal Transfer PRFs bypass the Approved Level 2 step.

Sammish 2026-05-16 (Jithin #1): IT vouchers don't need an L2 review —
they're just moving money between bank accounts owned by the same
company group, so a Finance Manager L1 sign-off is enough before the
Finance Controller releases.

Changes to the "Payment Request Form" workflow:
  1. Each existing "Approve Level 2" transition from Approved Level 1
     → Approved Level 2 gets a guard condition so it ONLY fires for
     non-Internal-Transfer rows:
         doc.payment_type != "Internal Transfer"
  2. A new "Release Payment" transition is added from Approved Level 1
     → Released for IT only, allowed by the same Finance Controller
     role that normally releases from Approved Level 2:
         doc.payment_type == "Internal Transfer"
  3. The existing "Release Payment" transition from Approved Level 2
     → Released stays untouched (used by non-IT vouchers).

Cancel transitions also need an IT branch: today, Cancel only works
from Approved L2 / Released for doc_status=1. After this change IT can
reach Released directly, so no edit there. From Approved L1 (still
doc_status=0) the existing Cancel→Rejected is fine for IT too.

Frappe's safe_eval for workflow conditions only allows int/float/long/
round and bare comparisons — string equality on doc.payment_type is
fine.

Idempotent.
"""
import frappe


WORKFLOW_NAME = "Payment Request Form"
IT_CONDITION_SKIP = 'doc.payment_type != "Internal Transfer"'
IT_CONDITION_ONLY = 'doc.payment_type == "Internal Transfer"'


def execute():
	if not frappe.db.exists("Workflow", WORKFLOW_NAME):
		print(f"[prf_internal_transfer_skip_l2] {WORKFLOW_NAME} workflow missing — skipping")
		return

	wf = frappe.get_doc("Workflow", WORKFLOW_NAME)
	changed = False

	# 1. Guard existing Approve Level 2 transitions.
	for t in wf.transitions:
		if (
			(t.state or "") == "Approved Level 1"
			and (t.action or "") == "Approve Level 2"
			and (t.next_state or "") == "Approved Level 2"
		):
			if (t.condition or "").strip() != IT_CONDITION_SKIP:
				t.condition = IT_CONDITION_SKIP
				changed = True

	# 2. Add new Release Payment transition for IT, if missing.
	has_it_release = False
	for t in wf.transitions:
		if (
			(t.state or "") == "Approved Level 1"
			and (t.action or "") == "Release Payment"
			and (t.next_state or "") == "Released"
		):
			has_it_release = True
			# If condition is missing or wrong, fix it.
			if (t.condition or "").strip() != IT_CONDITION_ONLY:
				t.condition = IT_CONDITION_ONLY
				changed = True
			break

	if not has_it_release:
		wf.append("transitions", {
			"state": "Approved Level 1",
			"action": "Release Payment",
			"next_state": "Released",
			"allowed": "Finance Controller",
			"allow_self_approval": 1,
			"condition": IT_CONDITION_ONLY,
		})
		changed = True

	if not changed:
		print("[prf_internal_transfer_skip_l2] workflow already configured — no changes")
		return

	wf.flags.ignore_permissions = True
	wf.flags.ignore_validate = True
	wf.save()
	frappe.db.commit()
	print(
		f"[prf_internal_transfer_skip_l2] updated workflow — total transitions={len(wf.transitions)}"
	)
