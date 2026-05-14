"""Internal Transfer now goes through L2 (like Internal Customer /
Supplier). Removes the previous L2-skip transitions so IT no longer
jumps Authorised → Released directly.

Sammish 2026-05-16 (Jithin final): all three inter-company scenarios
(Internal Transfer, Internal Customer, Internal Supplier) now use the
same flow:

    Draft → Authorised → Approve Level 2 → Approved L2 → Released

L1 Finance Manager review is skipped. L2 (GM/Director) is required
because money is moving between entities.

PaymentRequestForm.validate now sets is_internal_party=1 also when
payment_type == "Internal Transfer", so the existing
prf_internal_party_skip_l1 transitions (Authorised → Approve Level 2
for is_internal_party==1) cover IT too. This patch:

  1. Deletes the "Authorised → Release Payment" transition that the
     prior IT-skip-L2 patch added (was IT-only, no longer needed).
  2. Deletes the "Approved Level 1 → Release Payment" bridge for IT
     (no IT voucher should reach Approved L1 after the L1 skip; any
     pre-existing stuck data goes through the next L2 transition).
  3. Removes the `payment_type != "Internal Transfer"` clause from
     the "Approved Level 1 → Approve Level 2" condition so any IT
     voucher that's stuck at Approved L1 from before this patch can
     still proceed to L2.
  4. Simplifies the "Approve Level 1" guard. is_internal_party is
     now 1 for IT, so the redundant `payment_type != IT` clause is
     dropped. New condition:
         (doc.is_internal_party or 0) == 0

Idempotent.
"""
import frappe


DOCTYPE = "Payment Request Form"
NEW_L1_GUARD = '(doc.is_internal_party or 0) == 0'


def _find_workflow_name():
	rows = frappe.get_all(
		"Workflow",
		filters={"document_type": DOCTYPE, "is_active": 1},
		fields=["name"],
		order_by="modified desc",
	)
	if rows:
		return rows[0]["name"]
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
		print(f"[prf_internal_transfer_keep_l2] no workflow for {DOCTYPE} — skipping")
		return

	wf = frappe.get_doc("Workflow", wf_name)
	original_count = len(wf.transitions)
	changed = False

	# 1+2. Remove IT-direct-release transitions (Authorised → Released
	#      and Approved Level 1 → Released for IT).
	keep = []
	removed = []
	for t in wf.transitions:
		state = (t.state or "").strip()
		action = (t.action or "").strip()
		next_state = (t.next_state or "").strip()
		cond = (t.condition or "").strip()
		if (
			(state == "Authorised" or state == "Approved Level 1")
			and action == "Release Payment"
			and next_state == "Released"
			and 'payment_type == "Internal Transfer"' in cond
		):
			removed.append((state, action, allowed_of(t)))
			changed = True
			continue
		keep.append(t)

	if removed:
		wf.set("transitions", keep)

	# 3. Drop the IT exclusion from "Approved Level 1 → Approve Level 2".
	#    Existing condition: doc.payment_type != "Internal Transfer"
	#    New condition: blank (unconditional). After this change there
	#    is no scenario where an IT voucher should not be able to go
	#    Approved L1 → Approved L2 — it just gets there via the bypass
	#    path normally.
	for t in wf.transitions:
		if (
			(t.state or "") == "Approved Level 1"
			and (t.action or "") == "Approve Level 2"
			and (t.next_state or "") == "Approved Level 2"
		):
			if (t.condition or "").strip():
				t.condition = ""
				changed = True

	# 4. Simplify the "Approve Level 1" guard. With is_internal_party=1
	#    for IT, the old `payment_type != "Internal Transfer" and ...`
	#    clause is redundant.
	for t in wf.transitions:
		if (
			(t.state or "") == "Authorised"
			and (t.action or "") == "Approve Level 1"
			and (t.next_state or "") == "Approved Level 1"
		):
			if (t.condition or "").strip() != NEW_L1_GUARD:
				t.condition = NEW_L1_GUARD
				changed = True

	if not changed:
		print("[prf_internal_transfer_keep_l2] workflow already configured — no changes")
		return

	wf.flags.ignore_permissions = True
	wf.flags.ignore_validate = True
	wf.save()
	frappe.db.commit()
	print(
		f"[prf_internal_transfer_keep_l2] updated workflow {wf_name!r} — "
		f"transitions {original_count}→{len(wf.transitions)} "
		f"(removed IT-direct-release={len(removed)})"
	)


def allowed_of(t):
	try:
		return (t.allowed or "").strip()
	except Exception:
		return ""
