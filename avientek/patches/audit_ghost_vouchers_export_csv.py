"""Patch B1 — audit ghost vouchers (docstatus=1 with missing GL / SLE)
and populate Ghost Voucher Repost Log rows for Accounts review.

Voucher types audited (GL-creating):
  - Sales Invoice, Purchase Invoice, Journal Entry, Payment Entry,
    Stock Entry, Delivery Note, Purchase Receipt

A doc is a 'ghost' if:
  - docstatus=1 AND
  - it should create GL entries AND none exist in tabGL Entry where
    voucher_type+voucher_no match, OR
  - it should create SLE AND none exist in tabStock Ledger Entry where
    voucher_type+voucher_no match.

For each ghost found, ensures a Ghost Voucher Repost Log row exists
with status='Pending Review' (or refreshes audit_notes / counts on
existing Pending Review rows). Doesn't touch Done / Ready / Failed.

Also exports a CSV snapshot to sites/<site>/private/files/ for offline
review.

Idempotent. Safe to re-run weekly.
"""
import csv
import os
import frappe
from frappe.utils import now_datetime


# Voucher types that must create GL entries on submit
GL_REQUIRED = ("Sales Invoice", "Purchase Invoice", "Journal Entry", "Payment Entry")
# Voucher types that must create SLE on submit
SLE_REQUIRED = ("Stock Entry", "Delivery Note", "Purchase Receipt")
ALL_VOUCHER_TYPES = GL_REQUIRED + SLE_REQUIRED


def _count_gl(voucher_type, voucher_no):
	return frappe.db.count("GL Entry", {
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"is_cancelled": 0,
	})


def _count_sle(voucher_type, voucher_no):
	return frappe.db.count("Stock Ledger Entry", {
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"is_cancelled": 0,
	})


def execute():
	ghosts = []
	ts = now_datetime()

	for vt in ALL_VOUCHER_TYPES:
		# Pull all submitted (docstatus=1) docs of this type
		# Limit to non-return docs for SLE check (returns may legitimately have 0 SLE in some flows)
		try:
			docs = frappe.get_all(
				vt,
				filters={"docstatus": 1},
				fields=["name", "company", "posting_date", "grand_total", "currency"]
				if vt != "Journal Entry"
				else ["name", "company", "posting_date", "total_debit AS grand_total"],
				limit_page_length=0,
			)
		except Exception as e:
			print(f"[audit_ghost_vouchers_export_csv] could not list {vt}: {e}")
			continue

		for d in docs:
			needs_gl = vt in GL_REQUIRED
			needs_sle = vt in SLE_REQUIRED
			gl_cnt = _count_gl(vt, d["name"]) if needs_gl else None
			sle_cnt = _count_sle(vt, d["name"]) if needs_sle else None

			missing_gl = needs_gl and gl_cnt == 0
			missing_sle = needs_sle and sle_cnt == 0

			if not (missing_gl or missing_sle):
				continue  # has its entries — not a ghost

			ghosts.append({
				"voucher_type": vt,
				"voucher_no": d["name"],
				"company": d.get("company"),
				"posting_date": d.get("posting_date"),
				"grand_total": d.get("grand_total") or 0,
				"currency": d.get("currency") or "",
				"missing_gl": int(bool(missing_gl)),
				"missing_sle": int(bool(missing_sle)),
				"gl_count_before": gl_cnt or 0,
				"sle_count_before": sle_cnt or 0,
			})

	print(f"[audit_ghost_vouchers_export_csv] found {len(ghosts)} ghost vouchers")

	# Sync into Ghost Voucher Repost Log
	inserted = 0
	refreshed = 0
	for g in ghosts:
		existing = frappe.db.get_value(
			"Ghost Voucher Repost Log",
			{"voucher_type": g["voucher_type"], "voucher_no": g["voucher_no"]},
			"name",
		)
		audit_note = (
			f"Detected {ts:%Y-%m-%d %H:%M}. "
			f"missing_gl={bool(g['missing_gl'])} missing_sle={bool(g['missing_sle'])} "
			f"gl_before={g['gl_count_before']} sle_before={g['sle_count_before']}"
		)
		if existing:
			doc = frappe.get_doc("Ghost Voucher Repost Log", existing)
			if doc.status in ("Done", "Ready", "Failed"):
				continue  # already in cleanup workflow
			doc.audit_notes = audit_note
			doc.gl_entries_before = g["gl_count_before"]
			doc.sle_entries_before = g["sle_count_before"]
			doc.value_at_risk = float(g["grand_total"])
			doc.save(ignore_permissions=True)
			refreshed += 1
		else:
			doc = frappe.new_doc("Ghost Voucher Repost Log")
			doc.voucher_type = g["voucher_type"]
			doc.voucher_no = g["voucher_no"]
			doc.company = g["company"]
			doc.posting_date = g["posting_date"]
			doc.grand_total = float(g["grand_total"] or 0)
			doc.currency = g["currency"]
			doc.gl_entries_before = g["gl_count_before"]
			doc.sle_entries_before = g["sle_count_before"]
			doc.value_at_risk = float(g["grand_total"] or 0)
			doc.audit_notes = audit_note
			doc.status = "Pending Review"
			doc.insert(ignore_permissions=True)
			inserted += 1

	# CSV export
	private = frappe.get_site_path("private", "files")
	os.makedirs(private, exist_ok=True)
	tag = ts.strftime("%Y%m%d_%H%M%S")
	path = os.path.join(private, f"ghost_vouchers_audit_{tag}.csv")
	with open(path, "w", newline="") as f:
		w = csv.writer(f)
		w.writerow(["Sl NO", "Voucher Type", "Voucher No", "Company",
		            "Posting Date", "Grand Total", "Currency",
		            "Missing GL", "Missing SLE", "GL Count", "SLE Count"])
		for i, g in enumerate(ghosts, 1):
			w.writerow([
				i, g["voucher_type"], g["voucher_no"], g["company"],
				g["posting_date"], g["grand_total"], g["currency"],
				g["missing_gl"], g["missing_sle"],
				g["gl_count_before"], g["sle_count_before"],
			])

	frappe.db.commit()
	frappe.clear_cache(doctype="Ghost Voucher Repost Log")
	print(
		f"[audit_ghost_vouchers_export_csv] inserted={inserted} refreshed={refreshed} "
		f"csv={path}"
	)
