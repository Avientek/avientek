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


def execute():
	ready = frappe.get_all(
		"Ghost Voucher Repost Log",
		filters={"status": "Ready", "ready_for_repost": 1},
		fields=["name", "voucher_type", "voucher_no"],
	)
	print(f"[repost_ghost_vouchers_bulk] {len(ready)} rows Ready for repost")

	done = 0
	skipped = 0
	failed = 0

	for r in ready:
		log = frappe.get_doc("Ghost Voucher Repost Log", r["name"])
		vt = r["voucher_type"]
		vn = r["voucher_no"]

		try:
			# Verify source doc still exists + is submitted
			if not frappe.db.exists(vt, vn):
				log.status = "Skipped"
				log.remarks = "Source voucher no longer exists"
				log.save(ignore_permissions=True)
				skipped += 1
				continue

			doc_status = frappe.db.get_value(vt, vn, "docstatus")
			if doc_status != 1:
				log.status = "Skipped"
				log.remarks = f"Source voucher docstatus={doc_status} (not submitted) — cannot repost"
				log.save(ignore_permissions=True)
				skipped += 1
				continue

			started = now_datetime()
			doc = frappe.get_doc(vt, vn)
			methods_called = []
			for method_name in LEDGER_METHODS.get(vt, ()):
				method = getattr(doc, method_name, None)
				if not method:
					continue
				# from_repost=True wakes idempotency guards in ERPNext's
				# StockController.make_gl_entries (otherwise it short-circuits
				# on docs that "should already have" entries).
				try:
					method(from_repost=True)
				except TypeError:
					method()
				methods_called.append(method_name)

			gl_after = _count_gl(vt, vn)
			sle_after = _count_sle(vt, vn)

			# Map called methods to a value the Select field accepts.
			# Field options: make_gl_entries / update_stock_ledger / both / manual.
			if len(methods_called) >= 2:
				repost_method_value = "both"
			elif methods_called:
				repost_method_value = methods_called[0]
			else:
				repost_method_value = "manual"

			# If the methods executed but produced 0 entries on a doc
			# that needed them, the root cause is upstream (typically
			# items have incoming_rate=0, or grand_total is 0, so there's
			# no value to write to the ledger). Mark Skipped with a
			# diagnostic note — Accounts must investigate at item level.
			gl_required = log.gl_entries_before == 0 and gl_after == 0 and vt in (
				"Sales Invoice", "Purchase Invoice", "Journal Entry", "Payment Entry",
				"Expense Claim", "Delivery Note", "Purchase Receipt",
			)
			sle_required = log.sle_entries_before == 0 and sle_after == 0 and vt in (
				"Stock Entry", "Delivery Note", "Purchase Receipt",
			)
			no_progress = gl_required or sle_required

			# Use direct DB writes (no doc.save) to skip the timestamp
			# check entirely — ledger methods invoked above can trigger
			# wildcard on_submit hooks that touch this row indirectly,
			# leaving doc.save() to fail with TimestampMismatchError.
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
						"Likely upstream issue: items have incoming_rate=0 / no cost basis, "
						"or doc grand_total=0. Accounts to investigate item valuation."
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
			frappe.db.set_value("Ghost Voucher Repost Log", r["name"], {
				"status": "Failed",
				"error_message": str(e)[:500],
				"repost_finished": now_datetime(),
			}, update_modified=True)
			failed += 1
			# Continue with next row

	frappe.db.commit()
	print(f"[repost_ghost_vouchers_bulk] done={done} skipped={skipped} failed={failed}")
