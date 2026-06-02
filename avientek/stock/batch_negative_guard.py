"""Independent submit-time guard against negative per-batch stock.

Sridhar 2026-06-01 — Phase 1 of the negative-stock cleanup plan.

Background: ERPNext v15's `get_stock_ledgers_batches` double-counts
SBB-linked Stock Ledger Entries (once via SLE.batch_no, once via
SBE.qty), making batches appear to have more stock than they really
do. The picker monkey-patch (commit 4aa6d0a, 2026-05-25) capped that
specific code path, but ERPNext core has many places that read batch
availability for validation, and some of them still use the buggy
function. The result was 438 negative batch buckets accumulated
between Sept 2024 and May 2026.

This module is the LAST LINE OF DEFENCE: a `before_submit` hook on
every stock-affecting doctype (Delivery Note, Sales Invoice, Stock
Entry, Purchase Receipt) that recomputes per-batch balance via DIRECT
SQL — bypassing ERPNext's buggy function — and blocks the submit if
any batch would land below 0. No data writes, no GL side-effects: it
only validates and throws a clear error pointing the user to
alternative batches with stock.

Skipped doctypes:
  - Stock Reconciliation: it's the tool that FIXES negative batches.
    Allowing it to bypass the guard is intentional.
  - Subcontracting / Manufacturing: out of scope for Phase 1. Add
    later if needed.
"""

import frappe
from frappe import _


# ---------------------------------------------------------------- public hook


def check_batches_remain_positive(doc, method=None):
	"""Block submits that would push any batch below 0.

	Hooked via `doc_events[<doctype>]["before_submit"]` in hooks.py.
	"""
	if not getattr(doc, "items", None):
		return

	# Rahul 2026-06-02: false-positive on Sales Invoice LTD-26-27-00303.
	# An SI/PI created from a DN/PR has update_stock=0 and does NOT write
	# to the Stock Ledger — the DN/PR already did. We must not validate
	# batch availability on these docs or every standard billing flow
	# breaks once the source batch's post-DN balance is low.
	if doc.doctype in ("Sales Invoice", "Purchase Invoice"):
		if not bool(getattr(doc, "update_stock", 0)):
			return

	# Collect (item, source_warehouse, batch_no, signed_qty_delta) tuples.
	# We only care about deltas that REDUCE a batch — adding stock can't
	# cause a negative.
	outward_deltas = _collect_outward_batch_deltas(doc)
	if not outward_deltas:
		return

	# Group same (item, warehouse, batch) tuples and sum deltas — handles
	# the case where a single doc has multiple rows hitting the same batch.
	grouped = {}
	for item, warehouse, batch_no, delta in outward_deltas:
		key = (item, warehouse, batch_no)
		grouped[key] = grouped.get(key, 0.0) + delta

	blockers = []
	for (item, warehouse, batch_no), delta in grouped.items():
		current = _get_current_batch_balance(item, warehouse, batch_no, exclude_voucher=doc.name)
		projected = current + delta
		if projected < -0.0001:
			blockers.append({
				"item": item,
				"warehouse": warehouse,
				"batch_no": batch_no,
				"current": current,
				"delta": delta,
				"projected": projected,
			})

	if not blockers:
		return

	# Build user-facing error with suggested alternative batches
	lines = []
	for b in blockers:
		alts = _get_alternative_batches(
			b["item"], b["warehouse"], exclude=b["batch_no"], min_qty=abs(b["delta"]),
		)
		alt_str = ", ".join(
			f"<b>{a['batch_no']}</b> ({a['balance']:.0f})" for a in alts[:5]
		)
		lines.append(_(
			"Batch <b>{0}</b> of item <b>{1}</b> in <b>{2}</b> would go to "
			"<b>{3:.2f}</b> (current: {4:.2f}, change: {5:+.2f})."
		).format(
			b["batch_no"], b["item"], b["warehouse"],
			b["projected"], b["current"], b["delta"],
		))
		if alt_str:
			lines.append(_(
				"&nbsp;&nbsp;&nbsp;&nbsp;Available batches with stock: {0}"
			).format(alt_str))
		else:
			lines.append(_(
				"&nbsp;&nbsp;&nbsp;&nbsp;No other batches in this warehouse have "
				"sufficient stock — contact Stock Manager."
			))

	frappe.throw(
		_("Submit blocked — this transaction would create negative batch stock.<br><br>{0}<br><br>"
		  "Please pick a different batch on the affected row(s).").format("<br>".join(lines)),
		title=_("Negative Batch Stock — Blocked"),
	)


# ---------------------------------------------------------------- collectors


def _collect_outward_batch_deltas(doc):
	"""Return list of (item, source_warehouse, batch_no, signed_qty) for every
	row that reduces a batch's stock. Inward-only rows are skipped.
	"""
	deltas = []
	doctype = doc.doctype

	for row in doc.items:
		item = getattr(row, "item_code", None)
		if not item:
			continue

		# Reads from either Serial and Batch Bundle (v15) or legacy batch_no
		sbb_name = getattr(row, "serial_and_batch_bundle", None)
		warehouse = _row_source_warehouse(doctype, row)
		if not warehouse:
			continue

		if sbb_name:
			# SBB mode — qty in `tabSerial and Batch Entry` is already signed
			# (negative for outward, positive for inward). Only outward (<0)
			# rows can drive a batch negative.
			entries = frappe.db.sql(
				"""
				SELECT batch_no, qty FROM `tabSerial and Batch Entry`
				WHERE parent = %s AND batch_no IS NOT NULL AND batch_no != ''
				""",
				(sbb_name,),
				as_dict=True,
			)
			for e in entries:
				q = float(e.qty or 0)
				if q < 0:
					deltas.append((item, warehouse, e.batch_no, q))
			continue

		# Legacy mode — direct batch_no on row
		batch_no = getattr(row, "batch_no", None)
		if not batch_no:
			continue
		qty = float(getattr(row, "qty", 0) or 0)
		if not qty:
			continue
		sign = _legacy_direction(doctype, doc)
		signed = sign * qty
		if signed < 0:
			deltas.append((item, warehouse, batch_no, signed))

	return deltas


def _row_source_warehouse(doctype, row):
	"""The warehouse from which stock is being taken on this row.

	For DN / SI / PR: the row's `warehouse` field.
	For Stock Entry: prefer `s_warehouse` (source); only check the SOURCE side.
	"""
	if doctype == "Stock Entry":
		# If a row has a source warehouse, that's where outward goes from.
		# Rows that only have t_warehouse (pure receipt) don't reduce stock.
		s = getattr(row, "s_warehouse", None)
		if s:
			return s
		return None
	return getattr(row, "warehouse", None)


def _legacy_direction(doctype, doc):
	"""Sign multiplier for legacy-mode (non-SBB) rows."""
	is_return = bool(getattr(doc, "is_return", 0))
	if doctype in ("Delivery Note", "Sales Invoice"):
		return 1 if is_return else -1
	if doctype == "Purchase Receipt":
		# A return PR sends stock OUT (negative); a normal PR brings IN (positive)
		return -1 if is_return else 1
	if doctype == "Stock Entry":
		# Source-warehouse row → always outward in legacy mode
		return -1
	return -1


# ----------------------------------------------------------- balance queries


def _get_current_batch_balance(item_code, warehouse, batch_no, exclude_voucher=None):
	"""True per-batch balance via direct SQL.

	Counts:
	  (a) Legacy SLEs with batch_no on the row AND no SBB attached.
	  (b) SBE.qty for SBB-linked SLEs (the new v15 model).
	Excludes cancelled SLEs and optionally the voucher we're validating
	(to avoid counting our own pending entries on re-submit / amend paths).
	"""
	legacy_extra = " AND sle.voucher_no != %(exclude)s" if exclude_voucher else ""
	sbe_extra = " AND sle.voucher_no != %(exclude)s" if exclude_voucher else ""

	params = {
		"item_code": item_code,
		"warehouse": warehouse,
		"batch_no": batch_no,
		"exclude": exclude_voucher or "",
	}

	res = frappe.db.sql(
		f"""
		SELECT
			COALESCE((
				SELECT SUM(sle.actual_qty)
				FROM `tabStock Ledger Entry` sle
				WHERE sle.item_code = %(item_code)s
				  AND sle.warehouse = %(warehouse)s
				  AND sle.batch_no = %(batch_no)s
				  AND sle.is_cancelled = 0
				  AND (sle.serial_and_batch_bundle IS NULL OR sle.serial_and_batch_bundle = '')
				  {legacy_extra}
			), 0)
			+
			COALESCE((
				SELECT SUM(sbe.qty)
				FROM `tabSerial and Batch Entry` sbe
				INNER JOIN `tabStock Ledger Entry` sle
					ON sle.serial_and_batch_bundle = sbe.parent
				WHERE sle.item_code = %(item_code)s
				  AND sle.warehouse = %(warehouse)s
				  AND sbe.batch_no = %(batch_no)s
				  AND sle.is_cancelled = 0
				  {sbe_extra}
			), 0)
			AS balance
		""",
		params,
	)
	return float(res[0][0]) if res and res[0] else 0.0


def _get_alternative_batches(item_code, warehouse, exclude=None, min_qty=0):
	"""List other batches in the same (item, warehouse) that have at least min_qty."""
	# Collect candidate batch_no values from both ledger sources
	candidates = frappe.db.sql(
		"""
		SELECT DISTINCT batch_no FROM (
			SELECT batch_no FROM `tabStock Ledger Entry`
			WHERE item_code = %(item_code)s AND warehouse = %(warehouse)s
			  AND batch_no IS NOT NULL AND batch_no != ''
			  AND is_cancelled = 0
			UNION
			SELECT sbe.batch_no FROM `tabSerial and Batch Entry` sbe
			INNER JOIN `tabStock Ledger Entry` sle
				ON sle.serial_and_batch_bundle = sbe.parent
			WHERE sle.item_code = %(item_code)s
			  AND sle.warehouse = %(warehouse)s
			  AND sbe.batch_no IS NOT NULL AND sbe.batch_no != ''
			  AND sle.is_cancelled = 0
		) x
		""",
		{"item_code": item_code, "warehouse": warehouse},
	)

	results = []
	for (batch_no,) in candidates:
		if not batch_no or batch_no == exclude:
			continue
		bal = _get_current_batch_balance(item_code, warehouse, batch_no)
		if bal >= min_qty:
			results.append({"batch_no": batch_no, "balance": bal})
	results.sort(key=lambda r: -r["balance"])
	return results
