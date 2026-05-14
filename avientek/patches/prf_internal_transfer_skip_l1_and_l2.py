"""Internal Transfer PRFs bypass BOTH Approved Level 1 AND Approved Level 2.

Sammish 2026-05-16 (Jithin update): the earlier
`prf_internal_transfer_skip_l2` only removed the L2 step for IT.
Jithin then confirmed IT vouchers don't need L1 either — Finance
Controller can release directly from Authorised. The workflow for IT
collapses to:

    Draft → Authorised → Released

Non-IT vouchers keep the full chain:

    Draft → Authorised → Approved L1 → Approved L2 → Released

Changes to the "Payment Request Form" workflow (idempotent):

  1. "Approve Level 1" transition (Authorised → Approved Level 1)
     gets the guard condition `doc.payment_type != "Internal Transfer"`
     so it only fires for non-IT rows.

  2. "Approve Level 2" transition (Approved Level 1 → Approved Level 2)
     keeps the same guard from the prior patch.

  3. NEW "Release Payment" transition (Authorised → Released) for IT
     only, allowed by Finance Controller, condition
     `doc.payment_type == "Internal Transfer"`.

  4. Existing "Release Payment" (Approved Level 1 → Released) for IT
     stays in place as a bridge for any IT vouchers stuck at Approved
     Level 1 from before this patch ran.

  5. Existing "Release Payment" (Approved Level 2 → Released) is
     untouched (used by non-IT vouchers).

Frappe's safe_eval for workflow conditions only allows int / float /
long / round and bare comparisons — string equality on
doc.payment_type is fine.

Idempotent. Safe to re-run.
"""
import frappe


# Sammish 2026-05-16: the create_payment_request_workflow patch names
# the workflow "Payment Request Form Approval" (suffix). Earlier
# revisions of this file looked for "Payment Request Form" and the
# guard silently logged "missing — skipping" on every site that had
# the proper v2 workflow. Now resolve dynamically by document_type so
# the patch lands no matter how the workflow was named.
DOCTYPE = "Payment Request Form"
IT_CONDITION_SKIP = 'doc.payment_type != "Internal Transfer"'
IT_CONDITION_ONLY = 'doc.payment_type == "Internal Transfer"'


def _find_workflow_name():
	"""Return the active workflow name for the PRF doctype, or None."""
	candidates = frappe.get_all(
		"Workflow",
		filters={"document_type": DOCTYPE, "is_active": 1},
		fields=["name"],
		order_by="modified desc",
	)
	if candidates:
		return candidates[0]["name"]
	# Fallback to any inactive workflow on the doctype — better than
	# nothing if the admin disabled the active flag temporarily.
	any_wf = frappe.get_all(
		"Workflow",
		filters={"document_type": DOCTYPE},
		fields=["name"],
		order_by="modified desc",
		limit=1,
	)
	return any_wf[0]["name"] if any_wf else None


def execute():
	wf_name = _find_workflow_name()
	if not wf_name:
		print(f"[prf_internal_transfer_skip_l1_and_l2] no workflow for {DOCTYPE} — skipping")
		return

	wf = frappe.get_doc("Workflow", wf_name)
	changed = False

	# 1. Guard "Approve Level 1" (Authorised → Approved Level 1) for non-IT.
	for t in wf.transitions:
		if (
			(t.state or "") == "Authorised"
			and (t.action or "") == "Approve Level 1"
			and (t.next_state or "") == "Approved Level 1"
		):
			if (t.condition or "").strip() != IT_CONDITION_SKIP:
				t.condition = IT_CONDITION_SKIP
				changed = True

	# 2. Guard "Approve Level 2" (Approved Level 1 → Approved Level 2) for non-IT.
	for t in wf.transitions:
		if (
			(t.state or "") == "Approved Level 1"
			and (t.action or "") == "Approve Level 2"
			and (t.next_state or "") == "Approved Level 2"
		):
			if (t.condition or "").strip() != IT_CONDITION_SKIP:
				t.condition = IT_CONDITION_SKIP
				changed = True

	# 3. NEW "Release Payment" (Authorised → Released) for IT only.
	has_it_release_from_auth = False
	for t in wf.transitions:
		if (
			(t.state or "") == "Authorised"
			and (t.action or "") == "Release Payment"
			and (t.next_state or "") == "Released"
		):
			has_it_release_from_auth = True
			if (t.condition or "").strip() != IT_CONDITION_ONLY:
				t.condition = IT_CONDITION_ONLY
				changed = True
			break

	if not has_it_release_from_auth:
		wf.append("transitions", {
			"state": "Authorised",
			"action": "Release Payment",
			"next_state": "Released",
			"allowed": "Finance Controller",
			"allow_self_approval": 1,
			"condition": IT_CONDITION_ONLY,
		})
		changed = True

	# 4. Bridge "Release Payment" (Approved Level 1 → Released) for IT.
	#    The previous prf_internal_transfer_skip_l2 patch was SUPPOSED
	#    to add this but silently no-op'd everywhere because it looked
	#    for the wrong workflow name. Add it here too — kept as a
	#    bridge for any IT voucher that's stuck at Approved Level 1
	#    from before this fix; condition is IT-only so non-IT vouchers
	#    don't see it.
	has_it_release_from_l1 = False
	for t in wf.transitions:
		if (
			(t.state or "") == "Approved Level 1"
			and (t.action or "") == "Release Payment"
			and (t.next_state or "") == "Released"
		):
			has_it_release_from_l1 = True
			if (t.condition or "").strip() != IT_CONDITION_ONLY:
				t.condition = IT_CONDITION_ONLY
				changed = True
			break

	if not has_it_release_from_l1:
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
		print("[prf_internal_transfer_skip_l1_and_l2] workflow already configured — no changes")
		return

	wf.flags.ignore_permissions = True
	wf.flags.ignore_validate = True
	wf.save()
	frappe.db.commit()
	print(
		f"[prf_internal_transfer_skip_l1_and_l2] updated workflow {wf_name!r} — total transitions={len(wf.transitions)}"
	)
