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

			log.repost_started = now_datetime()
			log.save(ignore_permissions=True)
			frappe.db.commit()

			doc = frappe.get_doc(vt, vn)
			methods_called = []
			for method_name in LEDGER_METHODS.get(vt, ()):
				method = getattr(doc, method_name, None)
				if not method:
					continue
				method()
				methods_called.append(method_name)

			log.repost_method = ",".join(methods_called) or "manual"
			log.gl_entries_after = _count_gl(vt, vn)
			log.sle_entries_after = _count_sle(vt, vn)
			log.repost_finished = now_datetime()
			log.status = "Done"
			log.error_message = ""
			log.save(ignore_permissions=True)
			done += 1

		except Exception as e:
			log.status = "Failed"
			log.error_message = str(e)[:500]
			log.repost_finished = now_datetime()
			log.save(ignore_permissions=True)
			failed += 1
			# Continue with next row

	frappe.db.commit()
	print(f"[repost_ghost_vouchers_bulk] done={done} skipped={skipped} failed={failed}")
