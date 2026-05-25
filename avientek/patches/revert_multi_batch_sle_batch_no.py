"""Revert SLE.batch_no on Stock Ledger Entries linked to multi-batch SBBs.

Sridhar 2026-05-25 (I017933 negatives across companies): the earlier
heal patch (heal_sle_batch_no_from_sbb) was designed for single-batch
SBBs — where the SLE has exactly one batch and the legacy
`SLE.batch_no` should equal that batch. Its inner SELECT picks the
FIRST batch entry from the SBB (`ORDER BY idx ASC LIMIT 1`) and stamps
it onto the SLE, regardless of whether the SBB carries one batch or
several.

For multi-batch SBBs (a single voucher line shipping/receiving several
batches in one go), ERPNext v15 stores the line as ONE SLE with
`batch_no = NULL` and keeps the per-batch breakdown inside the SBB.
The heal patch over-attributed the entire line qty to the first batch
in idx order. Real example:

    DN-FZCO-25-00845 line for I017933 @ FZCO-T1-RHS - A
      SBB entries:  BN07987 -1,  BN07988 -8,  BN07992 -3   (total -12)
      SLE row    :  qty -12  +  batch_no NULL  (correct)
      Post-heal  :  qty -12  +  batch_no BN07987  (WRONG — attributes
                                                   the whole -12 to BN07987)

Symptom on reports: Batch.batch_qty / Stock Balance shows phantom
negatives for the first batch in every multi-batch SBB. I017933
surfaced -11 / -7 / -3 / etc. across multiple warehouses with no
matching outflow event — the negatives are entirely a report artifact;
real stock is positive. Nobody enabled "Allow Negative Stock for
Batch"; ERPNext correctly validated the originating DN at submission
time using the SBB-level per-batch qty.

Fix: NULL-out SLE.batch_no on every SLE whose linked SBB has more
than one distinct batch_no in its entries. Then recompute
Batch.batch_qty for every affected batch using SBB rows directly
(same helper recompute_batch_qty_from_sbb_correct already uses).

Safe to re-run — once the SLE.batch_no is NULL it falls out of the
WHERE clause.

Leaves single-batch SBBs untouched (those are correct after the
original heal — Sridhar's BN03309 fix still works).
"""
import frappe
from frappe.utils import flt


def _total_batch_qty(batch_no):
	"""Sum Batch quantity from Serial and Batch Entry — submitted SBBs only."""
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
	# 1. Find every SBB whose entries reference more than one distinct batch_no.
	multi_batch_sbbs = frappe.db.sql(
		"""
		SELECT parent
		FROM `tabSerial and Batch Entry`
		WHERE batch_no IS NOT NULL AND batch_no != ''
		GROUP BY parent
		HAVING COUNT(DISTINCT batch_no) > 1
		""",
		as_dict=True,
	)
	multi_names = [r["parent"] for r in multi_batch_sbbs]
	print(f"[revert_multi_batch_sle_batch_no] Multi-batch SBBs: {len(multi_names)}")
	if not multi_names:
		return

	# 2. Collect every SLE that links to one of those SBBs AND currently has
	#    a non-empty batch_no. These are the rows the earlier heal over-attributed.
	#    Process in chunks to keep the IN list manageable.
	chunk_size = 500
	to_revert = []
	affected_batches = set()
	for i in range(0, len(multi_names), chunk_size):
		chunk = multi_names[i:i + chunk_size]
		rows = frappe.db.sql(
			"""
			SELECT name, batch_no
			FROM `tabStock Ledger Entry`
			WHERE serial_and_batch_bundle IN %(sbbs)s
			  AND batch_no IS NOT NULL AND batch_no != ''
			  AND is_cancelled = 0
			""",
			{"sbbs": tuple(chunk)},
			as_dict=True,
		)
		to_revert.extend(rows)
		for r in rows:
			if r["batch_no"]:
				affected_batches.add(r["batch_no"])

	print(f"[revert_multi_batch_sle_batch_no] SLEs to revert (batch_no -> NULL): {len(to_revert)}")
	print(f"[revert_multi_batch_sle_batch_no] Distinct batches whose qty needs recompute: {len(affected_batches)}")

	if not to_revert:
		return

	# 3. Apply: NULL the batch_no on every offender. Do it in chunks too.
	#    update_modified=False keeps audit-friendly timestamps intact on the SLE.
	reverted = 0
	for i in range(0, len(to_revert), chunk_size):
		chunk = [r["name"] for r in to_revert[i:i + chunk_size]]
		frappe.db.sql(
			"""
			UPDATE `tabStock Ledger Entry`
			SET batch_no = NULL
			WHERE name IN %(names)s
			""",
			{"names": tuple(chunk)},
		)
		reverted += len(chunk)

	# 4. Recompute Batch.batch_qty for every affected batch using SBB rows directly.
	recomputed = 0
	for batch_no in affected_batches:
		try:
			new_qty = _total_batch_qty(batch_no)
			frappe.db.set_value(
				"Batch", batch_no, "batch_qty", new_qty,
				update_modified=False,
			)
			recomputed += 1
		except Exception as e:
			frappe.log_error(
				message=f"Batch {batch_no}: {e}",
				title="revert_multi_batch_sle_batch_no",
			)

	frappe.db.commit()
	print(
		f"[revert_multi_batch_sle_batch_no] Reverted {reverted} SLE rows, "
		f"recomputed {recomputed}/{len(affected_batches)} batches"
	)
