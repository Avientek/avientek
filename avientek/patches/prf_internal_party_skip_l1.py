"""Internal Customer / Internal Supplier PRFs skip Approve Level 1.

Sammish 2026-05-16 (Jithin): inter-company payments — where the party
is an internal Customer (is_internal_customer = 1) or internal
Supplier (is_internal_supplier = 1) — don't need the Finance Manager
L1 review. They still need GM/Director L2 approval since it's a
payment to another entity, even if same group.

Workflow for internal-party PRFs:

    Draft → Authorised → Approved Level 2 → Released

Internal Transfer PRFs already collapse further (skip L2 too) — see
prf_internal_transfer_skip_l1_and_l2.

Non-internal Pay / Advance Pay keep the full chain:

    Draft → Authorised → Approved L1 → Approved L2 → Released

The PRF.is_internal_party Check field is auto-computed in
PaymentRequestForm.validate() from Customer.is_internal_customer /
Supplier.is_internal_supplier — workflow safe_eval can't call
frappe.db.get_value, so the boolean is materialised on the doc.

Changes (idempotent):

  1. The "Approve Level 1" transition (Authorised → Approved Level 1)
     gets an extended guard combining the existing IT skip with the
     new internal-party skip:
         doc.payment_type != "Internal Transfer" and (doc.is_internal_party or 0) == 0

  2. NEW "Approve Level 2" transition (Authorised → Approved Level 2)
     for internal-party PRFs only, allowed by General Manager and
     Director (the L2 roles), condition:
         (doc.is_internal_party or 0) == 1

  3. Existing IT transitions stay untouched (their conditions check
     payment_type == "Internal Transfer" which is mutually exclusive
     with the internal-party flag).

Frappe's safe_eval for workflow conditions only allows int / float /
long / round plus comparisons / and / or / not — the expressions above
use just comparisons and boolean ops, safe.

Idempotent. Safe to re-run.
"""
import frappe


DOCTYPE = "Payment Request Form"
L1_GUARD_CONDITION = (
	'doc.payment_type != "Internal Transfer" and (doc.is_internal_party or 0) == 0'
)
INTERNAL_PARTY_ONLY_CONDITION = '(doc.is_internal_party or 0) == 1'

# Roles that can approve L2 directly when skipping L1. Mirrors the
# Approved L1 → Approved L2 transition roles from
# create_payment_request_workflow.
L2_APPROVER_ROLES = ["General Manager", "Director"]


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
		print(f"[prf_internal_party_skip_l1] no workflow for {DOCTYPE} — skipping")
		return

	wf = frappe.get_doc("Workflow", wf_name)
	changed = False

	# 1. Tighten the guard on every existing "Approve Level 1"
	#    transition (Authorised → Approved Level 1). There may be
	#    several rows (one per allowed role).
	for t in wf.transitions:
		if (
			(t.state or "") == "Authorised"
			and (t.action or "") == "Approve Level 1"
			and (t.next_state or "") == "Approved Level 1"
		):
			if (t.condition or "").strip() != L1_GUARD_CONDITION:
				t.condition = L1_GUARD_CONDITION
				changed = True

	# 2. Add new "Approve Level 2" transitions from Authorised →
	#    Approved Level 2 for internal-party PRFs. One row per L2
	#    approver role; dedupe so re-runs don't add extras.
	existing_internal_l2_roles = set()
	for t in wf.transitions:
		if (
			(t.state or "") == "Authorised"
			and (t.action or "") == "Approve Level 2"
			and (t.next_state or "") == "Approved Level 2"
		):
			existing_internal_l2_roles.add((t.allowed or "").strip())
			# Refresh condition if it drifted.
			if (t.condition or "").strip() != INTERNAL_PARTY_ONLY_CONDITION:
				t.condition = INTERNAL_PARTY_ONLY_CONDITION
				changed = True

	for role in L2_APPROVER_ROLES:
		if role in existing_internal_l2_roles:
			continue
		wf.append("transitions", {
			"state": "Authorised",
			"action": "Approve Level 2",
			"next_state": "Approved Level 2",
			"allowed": role,
			"allow_self_approval": 1,
			"condition": INTERNAL_PARTY_ONLY_CONDITION,
		})
		changed = True

	if not changed:
		print("[prf_internal_party_skip_l1] workflow already configured — no changes")
		return

	wf.flags.ignore_permissions = True
	wf.flags.ignore_validate = True
	wf.save()
	frappe.db.commit()
	print(
		f"[prf_internal_party_skip_l1] updated workflow {wf_name!r} — total transitions={len(wf.transitions)}"
	)
