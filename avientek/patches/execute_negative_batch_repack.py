"""Patch A3 — execute Repack for Plan rows marked Ready.

For each Negative Batch Cleanup Plan row where:
  status=Ready AND path=REPACK AND ready_for_execution=1

Creates + submits a Stock Entry type=Repack at val_rate=0:
  Consume: donor batch qty=deficit, basic_rate=0
  Produce: negative batch qty=deficit, basic_rate=0

Both sides at val_rate=0 → zero net inventory value change → zero GL impact.
Net Bin total: unchanged. Per-batch attribution: corrected.

Idempotent: skips rows already Done. Per-row Failure preserved with
error_message so retries can be diagnosed.

This patch DOES NOT auto-tick ready_for_execution. Stock/Accounts
manager must mark each row Ready via the Cleanup Plan UI first.
That manual gate is the audit point.

Standard run: 0 docs if no rows are Ready (safe re-runs).
"""
import frappe
from frappe.utils import now_datetime


def _temporarily_enable_batch(batch_no):
	"""If batch is disabled, set disabled=0 and return True so caller
	can restore the flag after the Repack submits. Returns False if
	the batch was already enabled (no restore needed)."""
	if not batch_no:
		return False
	was_disabled = frappe.db.get_value("Batch", batch_no, "disabled")
	if was_disabled:
		frappe.db.set_value("Batch", batch_no, "disabled", 0, update_modified=False)
		return True
	return False


def _restore_batch_disabled(batch_no):
	if not batch_no:
		return
	frappe.db.set_value("Batch", batch_no, "disabled", 1, update_modified=False)


def _build_repack_se(plan_row):
	"""Build (don't submit) a Stock Entry Repack doc for a plan row."""
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Repack"
	se.purpose = "Repack"
	se.company = plan_row.company
	se.posting_date = frappe.utils.nowdate()
	se.posting_time = frappe.utils.nowtime()
	se.remarks = (
		f"Negative batch cleanup: move {plan_row.deficit_qty} unit(s) of "
		f"{plan_row.item_code} from donor batch {plan_row.donor_batch_no} "
		f"to negative batch {plan_row.neg_batch_no} at val_rate=0. "
		f"Plan ref: {plan_row.name}. Zero GL impact."
	)

	# Consume row (source)
	se.append("items", {
		"s_warehouse": plan_row.warehouse,
		"item_code": plan_row.item_code,
		"qty": plan_row.deficit_qty,
		"basic_rate": 0,
		"batch_no": plan_row.donor_batch_no,
		"use_serial_batch_fields": 1,
		"is_finished_item": 0,
	})
	# Produce row (target)
	se.append("items", {
		"t_warehouse": plan_row.warehouse,
		"item_code": plan_row.item_code,
		"qty": plan_row.deficit_qty,
		"basic_rate": 0,
		"batch_no": plan_row.neg_batch_no,
		"use_serial_batch_fields": 1,
		"is_finished_item": 1,
	})
	return se


def execute():
	ready_rows = frappe.get_all(
		"Negative Batch Cleanup Plan",
		filters={
			"status": "Ready",
			"path": "REPACK",
			"ready_for_execution": 1,
		},
		fields=["name"],
	)
	print(f"[execute_negative_batch_repack] {len(ready_rows)} ready rows queued for execution")

	# The cleanup Repack moves stock between two batches of the SAME
	# item+warehouse at val_rate=0. Net Bin qty is unchanged, but ERPNext
	# v15's between-SLE Bin check (between the consume-SLE and the
	# produce-SLE) sees a transient negative on the second SLE and throws
	# "X units of Item Y needed" — leaving the doc in a half-submitted
	# inconsistent state. Open the gate for the duration of this patch
	# and restore it on exit (try/finally). This is the same intent as
	# Stock Reconciliation, which is excluded from negative-stock checks.
	original_allow_neg_stock = frappe.db.get_single_value(
		"Stock Settings", "allow_negative_stock"
	) or 0
	if not original_allow_neg_stock:
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
		frappe.db.commit()

	done = 0
	failed = 0

	try:
		for r in ready_rows:
			plan = frappe.get_doc("Negative Batch Cleanup Plan", r["name"])
			# Some negative batches got disabled mid-life (e.g. a manual
			# cleanup attempt that disabled the batch but left dangling
			# negative SLEs). Frappe blocks transactions against disabled
			# batches. Temporarily re-enable both donor + target for the
			# Repack, restore the original flag after submit.
			neg_was_disabled = False
			donor_was_disabled = False
			try:
				neg_was_disabled = _temporarily_enable_batch(plan.neg_batch_no)
				donor_was_disabled = _temporarily_enable_batch(plan.donor_batch_no)
				se = _build_repack_se(plan)
				# Flag to bypass our own Phase 1 negative-batch guard for this
				# specific case — the consume + produce balance to zero on the
				# negative batch, but mid-validation the guard might trip
				# because intermediate per-batch calc shows the negative.
				# We trust this is a cleanup operation.
				se.flags.ignore_avientek_negative_batch_guard = True
				se.insert(ignore_permissions=True)
				se.submit()
				plan.executed_stock_entry = se.name
				plan.executed_on = now_datetime()
				plan.status = "Done"
				plan.error_message = ""
				plan.save(ignore_permissions=True)
				done += 1
			except Exception as e:
				plan.status = "Failed"
				plan.error_message = str(e)[:500]
				plan.save(ignore_permissions=True)
				failed += 1
				# Continue with other rows — don't fail the whole patch
			finally:
				# Restore disabled flag(s) so the batch returns to its
				# pre-cleanup state and can't be reused inadvertently.
				if neg_was_disabled:
					_restore_batch_disabled(plan.neg_batch_no)
				if donor_was_disabled:
					_restore_batch_disabled(plan.donor_batch_no)
	finally:
		# Restore Stock Settings to its original state — even if execute()
		# itself throws an unexpected error.
		if not original_allow_neg_stock:
			frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 0)
		frappe.db.commit()

	frappe.clear_cache()
	print(f"[execute_negative_batch_repack] done={done} failed={failed}")
