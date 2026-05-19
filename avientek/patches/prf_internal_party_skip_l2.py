"""Internal party PRFs (Internal Transfer / Internal Customer /
Internal Supplier) now skip Approved Level 2 instead of Approved
Level 1.

Jithin 2026-05-19 (reverses the 2026-05-16 final): all three internal
scenarios now follow the SAME flow as before, but with L1 instead of
L2 as the single approval step:

    Draft → Authorised → Approve Level 1 → Approved L1 → Released

External Pay / Advance Pay keeps the full chain:

    Draft → Authorised → Approve Level 1 → Approved L1 → Approve L2
          → Approved L2 → Released

This patch reshapes the existing workflow in 4 idempotent steps:

  1. Remove the internal-party exclusion from `Authorised → Approve
     Level 1`. Old condition restricted L1 to external parties only;
     new condition is blank (every party type goes through L1).
  2. Delete the `Authorised → Approve Level 2` transitions added for
     internal parties — they previously bypassed L1. With L1 now
     mandatory, these direct-L2 routes are wrong.
  3. Gate the existing `Approved Level 1 → Approve Level 2`
     transitions to external parties only. Internal parties stop at
     L1 and release from there.
  4. Add `Approved Level 1 → Release Payment → Released` for internal
     parties so they can release straight from L1.

Idempotent: re-runs check existing transitions before mutating.
"""

import frappe


DOCTYPE = "Payment Request Form"
INTERNAL_COND = '(doc.is_internal_party or 0) == 1 or doc.payment_type == "Internal Transfer"'
EXTERNAL_COND = '(doc.is_internal_party or 0) == 0 and doc.payment_type != "Internal Transfer"'


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
		print(f"[prf_internal_party_skip_l2] no workflow for {DOCTYPE} — skipping")
		return

	wf = frappe.get_doc("Workflow", wf_name)
	original_count = len(wf.transitions)
	changed = False

	# Step 1: clear the internal-exclusion condition on Authorised → L1
	for t in wf.transitions:
		if (
			(t.state or "") == "Authorised"
			and (t.action or "") == "Approve Level 1"
			and (t.next_state or "") == "Approved Level 1"
			and (t.condition or "").strip()
		):
			t.condition = ""
			changed = True

	# Step 2: drop the Authorised → Approve Level 2 (internal-direct) rows
	dropped_l2 = []
	keep = []
	for t in wf.transitions:
		if (
			(t.state or "") == "Authorised"
			and (t.action or "") == "Approve Level 2"
			and (t.next_state or "") == "Approved Level 2"
		):
			dropped_l2.append((t.allowed or "", (t.condition or "")[:80]))
			changed = True
			continue
		keep.append(t)
	if dropped_l2:
		wf.set("transitions", keep)

	# Step 3: gate Approved L1 → Approve L2 to external only
	for t in wf.transitions:
		if (
			(t.state or "") == "Approved Level 1"
			and (t.action or "") == "Approve Level 2"
			and (t.next_state or "") == "Approved Level 2"
		):
			if (t.condition or "").strip() != EXTERNAL_COND:
				t.condition = EXTERNAL_COND
				changed = True

	# Step 4: add Approved L1 → Release Payment → Released for internal
	# parties. Use Finance Controller (same role that releases from L2).
	have_internal_release = any(
		(t.state or "") == "Approved Level 1"
		and (t.action or "") == "Release Payment"
		and (t.next_state or "") == "Released"
		for t in wf.transitions
	)
	if not have_internal_release:
		wf.append("transitions", {
			"state": "Approved Level 1",
			"action": "Release Payment",
			"next_state": "Released",
			"allowed": "Finance Controller",
			"condition": INTERNAL_COND,
		})
		changed = True

	if not changed:
		print("[prf_internal_party_skip_l2] workflow already configured — no changes")
		return

	wf.flags.ignore_permissions = True
	wf.flags.ignore_validate = True
	wf.save()
	frappe.db.commit()
	print(
		f"[prf_internal_party_skip_l2] updated workflow {wf_name!r} — "
		f"transitions {original_count}→{len(wf.transitions)} "
		f"(dropped Authorised→L2={len(dropped_l2)})"
	)
