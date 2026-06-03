"""Patch B3 — repost GL / SLE for ghost vouchers marked Ready.

For each Ghost Voucher Repost Log row where:
  status='Ready' AND ready_for_repost=1

Calls the appropriate ledger-creating function on the underlying doc:
  - GL Entries:  doc.make_gl_entries() via frappe.get_doc(...).make_gl_entries()
  - SLE Entries: doc.update_stock_ledger() via frappe.get_doc(...).update_stock_ledger()

The doc must still be docstatus=1 (submitted) for these calls to be
valid — cancelled docs are skipped with a status='Skipped' note.

Idempotent: skips rows already Done. Tracks GL/SLE counts before and
after so Accounts can verify entries were actually created.

Per-row failures preserved with error_message for diagnosis. Continues
with the next row on failure.

Standard run with 0 Ready rows: 0 docs touched (safe re-runs).
"""
import frappe
from frappe.utils import now_datetime


# Voucher types and which ledger method(s) to call
LEDGER_METHODS = {
	"Sales Invoice":     ("make_gl_entries",),
	"Purchase Invoice":  ("make_gl_entries",),
	"Journal Entry":     ("make_gl_entries",),
	"Payment Entry":     ("make_gl_entries",),
	"Expense Claim":     ("make_gl_entries",),
	"Stock Entry":       ("update_stock_ledger", "make_gl_entries"),
	"Delivery Note":     ("update_stock_ledger", "make_gl_entries"),
	"Purchase Receipt":  ("update_stock_ledger", "make_gl_entries"),
}


def _count_gl(vt, vn):
	return frappe.db.count("GL Entry", {"voucher_type": vt, "voucher_no": vn, "is_cancelled": 0})


def _count_sle(vt, vn):
	return frappe.db.count("Stock Ledger Entry", {"voucher_type": vt, "voucher_no": vn, "is_cancelled": 0})


def _direct_insert_gl_for_jv(jv_name):
	"""Last-resort fallback: write GL Entry rows directly from JV.accounts
	via raw SQL, bypassing ERPNext's make_gl_entries() validation.

	Triggered when make_gl_entries() throws the misleading "Against
	Journal Entry X is already adjusted against some other voucher"
	error even when nothing actually references the JV. Verified on
	JV-AT-25-00373 (Sridhar 2026-06-03): the validation fires
	incorrectly via an India compliance hook, blocking a legitimate
	repost of a balanced JV.

	Caller must ensure Accounts Settings.acc_frozen_upto is lifted.
	Returns count of GL entries written. Raises on insert error.
	"""
	jv = frappe.get_doc("Journal Entry", jv_name)
	company_currency = frappe.db.get_value("Company", jv.company, "default_currency")
	fiscal_year = jv.get("fiscal_year") or frappe.db.get_value(
		"Fiscal Year",
		filters={"year_start_date": ["<=", jv.posting_date],
		         "year_end_date": [">=", jv.posting_date]},
		fieldname="name")

	# Clear any orphan entries first (partial submits)
	frappe.db.sql("DELETE FROM `tabGL Entry` WHERE voucher_no=%s", (jv_name,))

	written = 0
	for line in jv.accounts:
		ge = frappe.new_doc("GL Entry")
		ge.posting_date = jv.posting_date
		ge.transaction_date = jv.posting_date
		ge.account = line.account
		ge.account_currency = line.account_currency or company_currency
		ge.party_type = line.party_type or None
		ge.party = line.party or None
		ge.debit = line.debit
		ge.credit = line.credit
		ge.debit_in_account_currency = line.debit_in_account_currency
		ge.credit_in_account_currency = line.credit_in_account_currency
		ge.against = line.against_account or ""
		ge.against_voucher_type = line.reference_type or None
		ge.against_voucher = line.reference_name or None
		ge.voucher_type = "Journal Entry"
		ge.voucher_no = jv_name
		ge.voucher_subtype = jv.voucher_type or "Journal Entry"
		ge.cost_center = line.cost_center or None
		ge.project = line.project or None
		ge.company = jv.company
		ge.fiscal_year = fiscal_year
		ge.finance_book = jv.finance_book or None
		ge.remarks = jv.user_remark or ""
		ge.is_opening = jv.get("is_opening", "No")
		ge.is_advance = "No"
		ge.is_cancelled = 0
		ge.docstatus = 1
		ge.flags.ignore_permissions = True
		ge.flags.ignore_validate = True
		ge.flags.ignore_links = True
		ge.flags.ignore_mandatory = True
		ge.db_insert()
		written += 1
	return written


def execute():
	ready = frappe.get_all(
		"Ghost Voucher Repost Log",
		filters={"status": "Ready", "ready_for_repost": 1},
		fields=["name", "voucher_type", "voucher_no"],
	)
	print(f"[repost_ghost_vouchers_bulk] {len(ready)} rows Ready for repost")

	# Lift all date-freeze locks for the duration of this run.
	# Restored in the outer try/finally regardless of how we exit.
	# - Stock Settings.stock_frozen_upto blocks Stock Ledger Entry
	#   writes before the date.
	# - Accounts Settings.acc_frozen_upto blocks GL Entry writes
	#   before the date.
	# - Stock Settings.allow_negative_stock=0 blocks SLEs that would
	#   push a Bin negative (typical for legacy DN/SI cleanup).
	orig_stock_frozen = frappe.db.get_single_value("Stock Settings", "stock_frozen_upto") or ""
	orig_neg_stock = frappe.db.get_single_value("Stock Settings", "allow_negative_stock") or 0
	orig_acc_frozen = frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto") or ""

	if orig_stock_frozen:
		frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", "")
	if not orig_neg_stock:
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
	if orig_acc_frozen:
		frappe.db.set_single_value("Accounts Settings", "acc_frozen_upto", "")
	frappe.db.commit()

	done = 0
	skipped = 0
	failed = 0

	try:
		for r in ready:
			log = frappe.get_doc("Ghost Voucher Repost Log", r["name"])
			vt = r["voucher_type"]
			vn = r["voucher_no"]

			try:
				# Verify source doc still exists + is submitted
				if not frappe.db.exists(vt, vn):
					frappe.db.set_value("Ghost Voucher Repost Log", r["name"], {
						"status": "Skipped",
						"remarks": "Source voucher no longer exists",
					}, update_modified=True)
					skipped += 1
					continue

				doc_status = frappe.db.get_value(vt, vn, "docstatus")
				if doc_status != 1:
					frappe.db.set_value("Ghost Voucher Repost Log", r["name"], {
						"status": "Skipped",
						"remarks": f"Source voucher docstatus={doc_status} (not submitted) — cannot repost",
					}, update_modified=True)
					skipped += 1
					continue

				started = now_datetime()
				doc = frappe.get_doc(vt, vn)
				methods_called = []
				for method_name in LEDGER_METHODS.get(vt, ()):
					method = getattr(doc, method_name, None)
					if not method:
						continue
					# from_repost=True wakes ERPNext's StockController.
					# make_gl_entries idempotency guard (otherwise it
					# short-circuits on already-submitted docs).
					try:
						method(from_repost=True)
					except TypeError:
						method()
					methods_called.append(method_name)

				gl_after = _count_gl(vt, vn)
				sle_after = _count_sle(vt, vn)

				# Field options on `repost_method` Select:
				# make_gl_entries / update_stock_ledger / both / manual
				if len(methods_called) >= 2:
					repost_method_value = "both"
				elif methods_called:
					repost_method_value = methods_called[0]
				else:
					repost_method_value = "manual"

				# If methods ran but produced 0 entries on a doc that
				# needed them, root cause is upstream (items have
				# incoming_rate=0, all non-stock, or doc grand_total=0).
				# Mark Skipped with diagnostic so Accounts investigates.
				gl_required = log.gl_entries_before == 0 and gl_after == 0 and vt in (
					"Sales Invoice", "Purchase Invoice", "Journal Entry", "Payment Entry",
					"Expense Claim", "Delivery Note", "Purchase Receipt",
				)
				sle_required = log.sle_entries_before == 0 and sle_after == 0 and vt in (
					"Stock Entry", "Delivery Note", "Purchase Receipt",
				)
				no_progress = gl_required or sle_required

				# Direct DB writes (no doc.save) — the ledger methods
				# trigger wildcard on_submit hooks that touch this row
				# indirectly, which races against doc.save's
				# TimestampMismatch check.
				if no_progress:
					frappe.db.set_value("Ghost Voucher Repost Log", log.name, {
						"repost_started": started,
						"repost_method": repost_method_value,
						"gl_entries_after": gl_after,
						"sle_entries_after": sle_after,
						"repost_finished": now_datetime(),
						"status": "Skipped",
						"error_message": (
							"Repost methods executed but produced 0 entries. "
							"Likely upstream issue: items have incoming_rate=0 / "
							"no cost basis, all items non-stock, or doc "
							"grand_total=0. Accounts to investigate at item level."
						),
					}, update_modified=True)
					skipped += 1
				else:
					frappe.db.set_value("Ghost Voucher Repost Log", log.name, {
						"repost_started": started,
						"repost_method": repost_method_value,
						"gl_entries_after": gl_after,
						"sle_entries_after": sle_after,
						"repost_finished": now_datetime(),
						"status": "Done",
						"error_message": "",
					}, update_modified=True)
					done += 1

			except Exception as e:
				err_msg = str(e)
				# JV-specific fallback: if the misleading
				# "already adjusted against some other voucher"
				# validation fires AND nothing actually references
				# this JV, write GL Entries directly via SQL.
				if (vt == "Journal Entry"
				    and "already adjusted" in err_msg
				    and not frappe.db.exists("Journal Entry Account",
				                             {"reference_type": "Journal Entry",
				                              "reference_name": vn, "docstatus": 1})
				    and not frappe.db.exists("Payment Entry Reference",
				                             {"reference_doctype": "Journal Entry",
				                              "reference_name": vn})):
					try:
						frappe.db.rollback()
						written = _direct_insert_gl_for_jv(vn)
						frappe.db.commit()
						frappe.db.set_value("Ghost Voucher Repost Log", r["name"], {
							"status": "Done",
							"repost_method": "manual",
							"gl_entries_after": written,
							"repost_finished": now_datetime(),
							"error_message": "",
							"remarks": "Direct SQL insert fallback — make_gl_entries blocked by misleading validation",
						}, update_modified=True)
						done += 1
						continue
					except Exception as e2:
						err_msg = f"Fallback also failed: {e2}"
				frappe.db.set_value("Ghost Voucher Repost Log", r["name"], {
					"status": "Failed",
					"error_message": err_msg[:500],
					"repost_finished": now_datetime(),
				}, update_modified=True)
				failed += 1
				# Continue with next row

	finally:
		# Restore Stock + Accounts freezes regardless of how we exit
		frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", orig_stock_frozen or "")
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", orig_neg_stock or 0)
		frappe.db.set_single_value("Accounts Settings", "acc_frozen_upto", orig_acc_frozen or "")
		frappe.db.commit()

	print(f"[repost_ghost_vouchers_bulk] done={done} skipped={skipped} failed={failed}")
