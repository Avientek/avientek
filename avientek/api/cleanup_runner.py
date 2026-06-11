"""REST-callable wrappers for cleanup executor patches.

Sridhar 2026-06-03 — the cleanup patches (A3 negative-batch Repack and B3
Ghost Voucher repost) are `execute()` functions in patch modules, not
@frappe.whitelist()'d, so they can't be triggered via /api/method.

This module exposes thin whitelisted wrappers so the executors can be
fired from the REST API after Ready rows are marked. System Manager
permission is required.
"""
import frappe
from frappe import _


def _ensure_system_manager():
	if "System Manager" not in frappe.get_roles(frappe.session.user):
		frappe.throw(
			_("System Manager role required to trigger cleanup executors."),
			frappe.PermissionError,
		)


@frappe.whitelist()
def run_ghost_voucher_repost():
	"""Trigger Patch B3 — bulk repost of Ghost Voucher Repost Log rows
	with status=Ready AND ready_for_repost=1.

	Returns counts of done/skipped/failed for the caller to display.
	"""
	_ensure_system_manager()
	from avientek.patches.repost_ghost_vouchers_bulk import execute
	execute()
	# Re-pull counts to give the caller a useful response
	return {
		"done": frappe.db.count("Ghost Voucher Repost Log", {"status": "Done"}),
		"skipped": frappe.db.count("Ghost Voucher Repost Log", {"status": "Skipped"}),
		"failed": frappe.db.count("Ghost Voucher Repost Log", {"status": "Failed"}),
		"ready_remaining": frappe.db.count("Ghost Voucher Repost Log", {"status": "Ready"}),
	}


@frappe.whitelist()
def run_negative_batch_repack():
	"""Trigger Patch A3 — Repack execution for Negative Batch Cleanup Plan
	rows with status=Ready AND ready_for_execution=1.
	"""
	_ensure_system_manager()
	from avientek.patches.execute_negative_batch_repack import execute
	execute()
	return {
		"done": frappe.db.count("Negative Batch Cleanup Plan", {"status": "Done"}),
		"failed": frappe.db.count("Negative Batch Cleanup Plan", {"status": "Failed"}),
		"ready_remaining": frappe.db.count("Negative Batch Cleanup Plan", {"status": "Ready"}),
	}


@frappe.whitelist()
def promote_all_ghost_vouchers_ready():
	"""Mass-promote all Pending Review GVRL rows to Ready. Used by the
	cleanup workflow after Accounts review confirms the queue is OK to
	process in bulk. Returns count promoted.
	"""
	_ensure_system_manager()
	frappe.db.sql("""
		UPDATE `tabGhost Voucher Repost Log`
		SET status='Ready', ready_for_repost=1
		WHERE status='Pending Review'
	""")
	frappe.db.commit()
	return {"ready": frappe.db.count("Ghost Voucher Repost Log", {"status": "Ready"})}


@frappe.whitelist()
def promote_all_negative_batches_ready():
	"""Mass-promote all Pending NBCP rows to Ready."""
	_ensure_system_manager()
	frappe.db.sql("""
		UPDATE `tabNegative Batch Cleanup Plan`
		SET status='Ready', ready_for_execution=1
		WHERE status='Pending'
	""")
	frappe.db.commit()
	return {"ready": frappe.db.count("Negative Batch Cleanup Plan", {"status": "Ready"})}


@frappe.whitelist()
def fix_corrupted_freeze_settings():
	"""Sridhar/Venkatesh 2026-06-11: live-fix corrupted None values on
	the Single-doctype date / link fields that ERPNext's frozen-date
	guards compare against. Sister API to the
	`normalize_freeze_setting_nones` patch that runs on every migrate;
	this lets us unblock prod without waiting for the next deploy if
	the same corruption recurs.

	The crash mode it prevents:
	    erpnext/stock/doctype/stock_ledger_entry/stock_ledger_entry.py:252
	    `getdate(self.posting_date) <= getdate(stock_settings.stock_frozen_upto)`
	    TypeError: '<=' not supported between instances of
	               'datetime.date' and 'NoneType'

	Sets `stock_frozen_upto` / `stock_auth_role` / `acc_frozen_upto` /
	`frozen_accounts_modifier` to '' when their stored value is None.
	Empty string is unambiguous — every Frappe and ERPNext guard treats
	it as falsy and short-circuits before any date comparison.

	System Manager only. Idempotent. Read-only diagnostic field
	included in the response so the caller can confirm.
	"""
	_ensure_system_manager()
	targets = [
		("Stock Settings",    "stock_frozen_upto"),
		("Stock Settings",    "stock_auth_role"),
		("Accounts Settings", "acc_frozen_upto"),
		("Accounts Settings", "frozen_accounts_modifier"),
	]
	fixed = []
	for doctype, field in targets:
		cur = frappe.db.get_single_value(doctype, field)
		if cur is None:
			frappe.db.set_single_value(doctype, field, "")
			fixed.append({"doctype": doctype, "field": field})
	if fixed:
		frappe.db.commit()
		for doctype, _ in targets:
			try:
				frappe.clear_cache(doctype=doctype)
			except Exception:
				pass
	return {"fixed": fixed, "count": len(fixed)}
