"""Heal SLE.batch_no for SLEs linked to a Serial and Batch Bundle.

Sridhar 2026-05-24 (Batch BN03309 / Item I017971 / Credit Note
CRN-LLC-25-00002-1): Stock Balance report showed batch qty = 0 for a
batch that physically had 2 units returned from a customer. The SBB
SABB-00008224 correctly recorded +2 inward, but the related SLE
MAT-SLE-2025-10619 has `batch_no = NULL`. ERPNext's
`erpnext.stock.doctype.batch.batch.get_batch_qty` (and the Stock
Balance report) query `tabStock Ledger Entry WHERE batch_no = %s`
— so a NULL legacy field hides the actual qty.

Root cause: in ERPNext v15, batch tracking moved from
`Stock Ledger Entry.batch_no` (legacy direct field) to the
Serial and Batch Bundle doctype as the source of truth. Some code
paths (notably Credit Notes with `is_return=1, update_stock=1` that
create fresh batches via SBB) don't backfill the legacy SLE field.
`Batch.batch_qty` + most batch UIs still query the legacy field, so
the result is a "ghost batch" — SBB shows the qty, but Batch master
and Stock Balance say zero.

This patch is idempotent — finds every active SLE whose
`batch_no IS NULL/empty` AND has a non-empty
`serial_and_batch_bundle` link, looks up the SBB's first batch
entry, and backfills the SLE's `batch_no`. Then recomputes
`Batch.batch_qty` for every affected batch using the standard
`get_batch_qty` helper.

Safe to re-run — once SLE.batch_no is populated it falls out of the
WHERE clause.
"""
import frappe
from frappe.utils import flt


def _total_batch_qty(batch_no, item_code=None):
	"""Sum Batch quantity directly from Serial and Batch Entry rows
	(active, submitted SBBs only).

	Sridhar 2026-05-25 (BN15146 doubling): the first version of this
	patch used erpnext.stock.doctype.batch.batch.get_batch_qty which
	internally calls get_auto_batch_nos. That helper double-counts
	when an SLE has BOTH `batch_no` set AND a `serial_and_batch_bundle`
	link — which is exactly the state THIS patch leaves every healed
	SLE in. Result: Batch.batch_qty was stored at 2x the real qty
	(BN15146 net was 20, patch wrote 40).

	Fix: bypass the SLE.batch_no path entirely. SBB is the source of
	truth in v15 — query Serial and Batch Entry rows directly, joined
	to non-cancelled SBBs. This avoids the double-count regardless of
	whether SLE.batch_no is populated.
	"""
	row = frappe.db.sql(
		"""
		SELECT IFNULL(SUM(sbe.qty), 0) AS qty
		FROM `tabSerial and Batch Entry` sbe
		INNER JOIN `tabSerial and Batch Bundle` sbb
		  ON sbb.name = sbe.parent
		WHERE sbe.batch_no = %s
		  AND sbb.docstatus = 1
		  AND sbb.is_cancelled = 0
		""",
		batch_no,
	)
	return flt(row[0][0]) if row else 0


def execute():
	# 1. Discover broken SLEs (SBB linked + batch_no missing).
	broken = frappe.db.sql(
		"""
		SELECT
			sle.name AS sle_name,
			sle.item_code,
			sle.serial_and_batch_bundle AS sbb_name
		FROM `tabStock Ledger Entry` sle
		WHERE sle.is_cancelled = 0
		  AND (sle.batch_no IS NULL OR sle.batch_no = '')
		  AND sle.serial_and_batch_bundle IS NOT NULL
		  AND sle.serial_and_batch_bundle != ''
		""",
		as_dict=True,
	)
	print(f"[heal_sle_batch_no_from_sbb] Found {len(broken)} SLEs with linked SBB but blank batch_no")
	if not broken:
		return

	# 2. Backfill each SLE.batch_no from its SBB's first batch entry.
	healed = 0
	affected_batches = set()
	for row in broken:
		bn_rows = frappe.db.sql(
			"""
			SELECT batch_no FROM `tabSerial and Batch Entry`
			WHERE parent = %s
			  AND batch_no IS NOT NULL AND batch_no != ''
			ORDER BY idx ASC
			LIMIT 1
			""",
			row["sbb_name"],
			as_dict=True,
		)
		if not bn_rows:
			# SBB carries serials only (no batch) — nothing to heal here.
			continue
		bn = bn_rows[0]["batch_no"]
		frappe.db.set_value(
			"Stock Ledger Entry", row["sle_name"], "batch_no", bn,
			update_modified=False,
		)
		affected_batches.add((bn, row["item_code"]))
		healed += 1

	# 3. Recompute Batch.batch_qty for every affected batch.
	# get_batch_qty(batch_no, item_code) returns a list of per-warehouse
	# rows when no specific warehouse is passed — sum across them for
	# the total stored on tabBatch.batch_qty.
	recomputed = 0
	for batch_no, item_code in affected_batches:
		try:
			new_qty = _total_batch_qty(batch_no, item_code)
			frappe.db.set_value(
				"Batch", batch_no, "batch_qty", new_qty,
				update_modified=False,
			)
			recomputed += 1
		except Exception as e:
			# log_error truncates title at 140 chars — pass a short
			# title and stuff the long traceback into the body.
			frappe.log_error(
				message=f"Batch {batch_no} (item {item_code}): {e}",
				title="SLE batch_no heal",
			)

	frappe.db.commit()
	print(
		f"[heal_sle_batch_no_from_sbb] Healed {healed} SLE rows, "
		f"recomputed {recomputed} batches "
		f"(of {len(affected_batches)} affected)"
	)
