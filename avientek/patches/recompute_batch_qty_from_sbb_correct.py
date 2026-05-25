"""Recompute Batch.batch_qty from SBB rows directly (one-shot fix).

Sridhar 2026-05-25 follow-up to BN15146 doubling: the previous
heal_sle_batch_no_from_sbb patch (committed b3eb1c8 on 2026-05-24)
fed `get_batch_qty` for the batch_qty recompute. That ERPNext helper
internally calls get_auto_batch_nos which double-counts when an SLE
has BOTH `batch_no` set AND a `serial_and_batch_bundle` link —
exactly the state our heal patch leaves every healed SLE in. Result:
Batch.batch_qty was written at 2x the real qty for the 15,536 batches
the heal patch touched.

The heal patch's _total_batch_qty helper has been corrected to query
SBB rows directly, but Frappe's patch system tracks executed patches
in tabPatch Log and won't re-run the corrected logic on a normal
migrate. This patch is a new entry that forces the corrected
recompute to run once on every site.

Logic: for every Batch that has a non-zero stored batch_qty OR has
linked SBB entries, recompute batch_qty as
  SUM(Serial and Batch Entry.qty)
across all active (docstatus=1, not cancelled) SBB rows referencing
that batch. Update Batch.batch_qty in place.

Safe to re-run — pure recompute, no state mutation beyond
Batch.batch_qty.
"""
import frappe
from frappe.utils import flt


def execute():
	if not frappe.db.has_table("Serial and Batch Entry"):
		print("[recompute_batch_qty_from_sbb_correct] SBB tables missing — skipped")
		return

	# Walk every batch that either has a non-zero stored qty OR shows
	# up in any active SBB entry. Either side could need correction.
	# The UNION-based discovery is cheap (single query each).
	batches = frappe.db.sql(
		"""
		SELECT DISTINCT name FROM `tabBatch`
		WHERE IFNULL(batch_qty, 0) != 0
		UNION
		SELECT DISTINCT sbe.batch_no AS name
		FROM `tabSerial and Batch Entry` sbe
		INNER JOIN `tabSerial and Batch Bundle` sbb
		  ON sbb.name = sbe.parent
		WHERE sbb.docstatus = 1
		  AND sbb.is_cancelled = 0
		  AND sbe.batch_no IS NOT NULL
		  AND sbe.batch_no != ''
		""",
		as_dict=True,
	)
	print(f"[recompute_batch_qty_from_sbb_correct] Checking {len(batches)} batches")

	updated = 0
	cleared = 0
	for b in batches:
		batch_name = b["name"]
		if not batch_name:
			continue
		row = frappe.db.sql(
			"""
			SELECT IFNULL(SUM(sbe.qty), 0)
			FROM `tabSerial and Batch Entry` sbe
			INNER JOIN `tabSerial and Batch Bundle` sbb
			  ON sbb.name = sbe.parent
			WHERE sbe.batch_no = %s
			  AND sbb.docstatus = 1
			  AND sbb.is_cancelled = 0
			""",
			batch_name,
		)
		new_qty = flt(row[0][0]) if row else 0
		current = flt(frappe.db.get_value("Batch", batch_name, "batch_qty"))
		if abs(new_qty - current) < 0.001:
			continue
		frappe.db.set_value(
			"Batch", batch_name, "batch_qty", new_qty,
			update_modified=False,
		)
		updated += 1
		if new_qty == 0:
			cleared += 1

	frappe.db.commit()
	print(
		f"[recompute_batch_qty_from_sbb_correct] Updated batch_qty on "
		f"{updated} batches (of which {cleared} dropped to zero)"
	)
