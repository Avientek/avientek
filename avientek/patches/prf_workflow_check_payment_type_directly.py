"""Make the PRF workflow check payment_type directly + backfill
is_internal_party on existing docs so existing IT / Internal Party
PRFs immediately route through Approve Level 2 (skip L1) without
needing a re-save.

Sammish 2026-05-16 (Jithin caught it on AVWLL-00346): the prior patch
only set `is_internal_party=1` in validate, so existing PRFs created
before today still had the flag at 0 even after migrate. The workflow
condition `(doc.is_internal_party or 0) == 0` evaluated to TRUE for
an Internal Transfer voucher created yesterday → L1 button stayed
visible.

Fix:
  1. Widen the workflow conditions to check `payment_type` directly
     too, so the L1 button hides for IT vouchers regardless of
     whether is_internal_party was backfilled:

       "Approve Level 1" guard (Authorised → Approved L1):
         doc.payment_type != "Internal Transfer" and (doc.is_internal_party or 0) == 0

       "Approve Level 2" from Authorised guard (the bypass for
       internal-party):
         doc.payment_type == "Internal Transfer" or (doc.is_internal_party or 0) == 1

  2. SQL backfill: set is_internal_party=1 on every existing PRF that
     should have it:
       - payment_type == "Internal Transfer"
       - party_type == "Customer" AND Customer.is_internal_customer = 1
       - party_type == "Supplier" AND Supplier.is_internal_supplier = 1

     Uses raw UPDATE with update_modified=False so audit timestamps
     don't churn. Safe — only flips 0 → 1, never 1 → 0.

Idempotent.
"""
import frappe


DOCTYPE = "Payment Request Form"
L1_GUARD = (
	'doc.payment_type != "Internal Transfer" and (doc.is_internal_party or 0) == 0'
)
L2_FROM_AUTH_GUARD = (
	'doc.payment_type == "Internal Transfer" or (doc.is_internal_party or 0) == 1'
)


def _find_workflow_name():
	rows = frappe.get_all(
		"Workflow",
		filters={"document_type": DOCTYPE, "is_active": 1},
		fields=["name"],
		order_by="modified desc",
	)
	if rows:
		return rows[0]["name"]
	return None


def execute():
	# Part 1 — workflow condition update
	wf_name = _find_workflow_name()
	if wf_name:
		wf = frappe.get_doc("Workflow", wf_name)
		changed = False
		for t in wf.transitions:
			state = (t.state or "").strip()
			action = (t.action or "").strip()
			next_state = (t.next_state or "").strip()
			if state == "Authorised" and action == "Approve Level 1" and next_state == "Approved Level 1":
				if (t.condition or "").strip() != L1_GUARD:
					t.condition = L1_GUARD
					changed = True
			elif state == "Authorised" and action == "Approve Level 2" and next_state == "Approved Level 2":
				if (t.condition or "").strip() != L2_FROM_AUTH_GUARD:
					t.condition = L2_FROM_AUTH_GUARD
					changed = True
		if changed:
			wf.flags.ignore_permissions = True
			wf.flags.ignore_validate = True
			wf.save()
			print(f"[prf_workflow_check_payment_type_directly] workflow conditions updated on {wf_name!r}")
		else:
			print(f"[prf_workflow_check_payment_type_directly] workflow conditions already up-to-date")
	else:
		print(f"[prf_workflow_check_payment_type_directly] no workflow for {DOCTYPE} — workflow step skipped")

	# Part 2 — SQL backfill of is_internal_party on existing PRFs.
	# Only flip 0 → 1 so re-runs are no-ops.
	#
	# Sammish 2026-05-15 (Frappe Cloud migrate fail): patches.txt runs
	# BEFORE schema sync, so on a first migrate after the Custom Field
	# was added the column doesn't exist yet. The next run (after the
	# field syncs in via fixtures) picks up the backfill. Guard with
	# has_column so we don't crash the migrate.
	if not frappe.db.has_column("Payment Request Form", "is_internal_party"):
		print(
			"[prf_workflow_check_payment_type_directly] is_internal_party column "
			"not yet synced — skipping SQL backfill (will run on next migrate)"
		)
		return

	it_rows = frappe.db.sql(
		"""UPDATE `tabPayment Request Form`
		   SET is_internal_party = 1
		   WHERE payment_type = 'Internal Transfer'
		     AND COALESCE(is_internal_party, 0) = 0""",
	)
	it_affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

	cust_rows = frappe.db.sql(
		"""UPDATE `tabPayment Request Form` prf
		   JOIN `tabCustomer` c ON c.name = prf.party
		   SET prf.is_internal_party = 1
		   WHERE prf.party_type = 'Customer'
		     AND c.is_internal_customer = 1
		     AND COALESCE(prf.is_internal_party, 0) = 0""",
	)
	cust_affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

	sup_rows = frappe.db.sql(
		"""UPDATE `tabPayment Request Form` prf
		   JOIN `tabSupplier` s ON s.name = prf.party
		   SET prf.is_internal_party = 1
		   WHERE prf.party_type = 'Supplier'
		     AND s.is_internal_supplier = 1
		     AND COALESCE(prf.is_internal_party, 0) = 0""",
	)
	sup_affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

	frappe.db.commit()
	print(
		f"[prf_workflow_check_payment_type_directly] backfill — "
		f"IT={it_affected} internal_customer={cust_affected} internal_supplier={sup_affected}"
	)
