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
GL_REQUIRED = (
	"Sales Invoice", "Purchase Invoice", "Journal Entry", "Payment Entry",
	"Expense Claim",
)
# Voucher types that must create SLE on submit
SLE_REQUIRED = ("Stock Entry", "Delivery Note", "Purchase Receipt")
ALL_VOUCHER_TYPES = GL_REQUIRED + SLE_REQUIRED

# Per-doctype field map for amount + currency — Frappe doesn't have a
# universal "grand_total" field name. Journal Entry uses total_debit,
# Expense Claim uses total_claimed_amount, etc. Anything not listed
# falls back to ("grand_total", "currency").
AMOUNT_FIELDS = {
	"Journal Entry": ("total_debit", None),
	"Expense Claim": ("total_claimed_amount", None),
	"Payment Entry": ("paid_amount", "paid_from_account_currency"),
	"Stock Entry":   ("total_amount", None),
}


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


# Item-bearing doctype → child-table doctype name
ITEM_CHILD = {
	"Sales Invoice":    "Sales Invoice Item",
	"Purchase Invoice": "Purchase Invoice Item",
	"Delivery Note":    "Delivery Note Item",
	"Purchase Receipt": "Purchase Receipt Item",
	"Stock Entry":      "Stock Entry Detail",
}


def _has_stock_item(voucher_type, voucher_no):
	"""True if any line item is a stock-tracked item.

	The original audit ignored this and flagged every transactional doc
	with 0 SLE/GL as a ghost. Reality: a DN/SI shipping only services
	(is_stock_item=0) correctly has no SLE, and a SI for services with
	zero grand_total has no GL — both are valid system states, not
	ghosts. Same false-positive pattern as the 528→1 negative-batch
	finding (mirroring an upstream bug in our own audit).
	"""
	child = ITEM_CHILD.get(voucher_type)
	if not child:
		# Doctype has no item table (JV, PE, EC) — always evaluate
		return True
	stock_items = frappe.db.sql(f"""
		SELECT 1 FROM `tab{child}` ci
		INNER JOIN `tabItem` i ON i.name = ci.item_code
		WHERE ci.parent = %s AND ci.parenttype = %s AND i.is_stock_item = 1
		LIMIT 1
	""", (voucher_no, voucher_type))
	return bool(stock_items)


def _has_any_amount(voucher_type, voucher_no, child_field, amount_field="amount"):
	"""True if any item line has non-zero amount.

	A SI with grand_total=0 and every line at 0 is a void/cancelled-like
	state — no GL entries are expected. Flagging it as a ghost is wrong.
	"""
	child = ITEM_CHILD.get(voucher_type)
	if not child:
		return True
	res = frappe.db.sql(f"""
		SELECT 1 FROM `tab{child}`
		WHERE parent = %s AND parenttype = %s
		  AND ABS(IFNULL({amount_field}, 0)) > 0.001
		LIMIT 1
	""", (voucher_no, voucher_type))
	return bool(res)


def execute():
	ghosts = []
	ts = now_datetime()

	for vt in ALL_VOUCHER_TYPES:
		# Pull all submitted (docstatus=1) docs of this type
		# Limit to non-return docs for SLE check (returns may legitimately have 0 SLE in some flows)
		amt_field, curr_field = AMOUNT_FIELDS.get(vt, ("grand_total", "currency"))
		fields = ["name", "company", "posting_date", f"{amt_field} AS grand_total"]
		if curr_field:
			fields.append(f"{curr_field} AS currency")

		try:
			docs = frappe.get_all(
				vt,
				filters={"docstatus": 1},
				fields=fields,
				limit_page_length=0,
			)
		except Exception as e:
			print(f"[audit_ghost_vouchers_export_csv] could not list {vt}: {e}")
			continue

		# Pre-fetch which docs have at least one stock item — major
		# filter to drop service-only DN/SI/etc. that legitimately have
		# no SLE / GL.
		has_stock_item = {}
		has_amount = {}
		if vt in ITEM_CHILD:
			child = ITEM_CHILD[vt]
			rows = frappe.db.sql(f"""
				SELECT ci.parent
				FROM `tab{child}` ci
				INNER JOIN `tabItem` i ON i.name = ci.item_code
				WHERE ci.parenttype = %s AND i.is_stock_item = 1
				GROUP BY ci.parent
			""", (vt,))
			has_stock_item = {r[0] for r in rows}
			# Amount field varies — for SI/PI/DN/PR it's `amount`, for SE it's `amount` too
			rows = frappe.db.sql(f"""
				SELECT parent FROM `tab{child}`
				WHERE parenttype = %s AND ABS(IFNULL(amount, 0)) > 0.001
				GROUP BY parent
			""", (vt,))
			has_amount = {r[0] for r in rows}

		for d in docs:
			# GL requirement: doctype is in GL_REQUIRED AND (no items OR has at least one stock item or non-zero amount)
			# For item-bearing doctypes, skip the GL check if all items are non-stock AND amount=0
			# A SI for $0 of services has no GL (and shouldn't).
			# A SI for $1000 of services HAS GL even with no stock items.
			# A DN with non-stock items only has no GL/SLE (services).
			needs_gl = vt in GL_REQUIRED
			needs_sle = vt in SLE_REQUIRED

			if vt in ITEM_CHILD:
				dn_has_stock = d["name"] in has_stock_item
				dn_has_amount = d["name"] in has_amount
				if needs_sle and not dn_has_stock:
					needs_sle = False  # service-only doc — no SLE expected
				if needs_gl and not dn_has_stock and not dn_has_amount:
					needs_gl = False  # zero-value void-like doc — no GL expected

			if not (needs_gl or needs_sle):
				continue  # nothing to detect on this doc

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
