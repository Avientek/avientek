"""Patch — backfill corrupted `outstanding_amount` / `base_outstanding_amount`
on historical Payment Request Reference rows.

Sridhar 2026-06-05 — companion to the JS mapper fix (commit 1b36c43)
and reader fixes (033a05b + this commit's report + apply-data fixes).

Background: a legacy JS mapper bug caused PI/SI rows added via the
single-picker path to store the AED-equivalent value in
`outstanding_amount` instead of the transaction-currency (EUR) value.
The print, report, and apply-data readers have been switched to prefer
`grand_total` (always FC) to mask the bug. This patch finishes the job
by fixing the underlying data on rows where:
  - currency != company_currency  (multi-currency PRF)
  - outstanding_amount ≈ base_grand_total  (looks like AED stored as FC)
  - grand_total ≠ outstanding_amount  (confirms drift)
  - grand_total > 0  (we have a valid FC source to copy from)

For each corrupt row, set:
  outstanding_amount = grand_total          (FC value)
  base_outstanding_amount = base_grand_total (already correct, normalize anyway)

Idempotent. Re-runs find no candidates after first run.
"""
import frappe
from frappe.utils import flt


TOLERANCE = 0.01


def execute():
	# Pull all child rows joined with parent for company lookup
	rows = frappe.db.sql("""
		SELECT
			prr.name,
			prr.parent,
			prr.currency,
			prr.outstanding_amount,
			prr.base_outstanding_amount,
			prr.grand_total,
			prr.base_grand_total,
			c.default_currency AS company_currency
		FROM `tabPayment Request Reference` prr
		INNER JOIN `tabPayment Request Form` prf ON prr.parent = prf.name
		INNER JOIN `tabCompany` c ON prf.company = c.name
		WHERE prr.currency IS NOT NULL AND prr.currency != ''
		  AND prr.currency != c.default_currency
		  AND prr.grand_total IS NOT NULL AND prr.grand_total > 0
	""", as_dict=True)

	print(f"[backfill_prf_reference_fc_amounts] scanning {len(rows)} multi-currency PRF reference rows")

	corrupt = []
	for r in rows:
		fc = flt(r.outstanding_amount or 0)
		base_grand = flt(r.base_grand_total or 0)
		grand = flt(r.grand_total or 0)
		if not fc or not base_grand or not grand:
			continue
		# Heuristic: outstanding_amount matches base_grand_total but
		# differs from grand_total → it's actually base (AED) value
		if abs(fc - base_grand) < TOLERANCE and abs(fc - grand) > TOLERANCE:
			corrupt.append(r)

	print(f"[backfill_prf_reference_fc_amounts] {len(corrupt)} corrupt rows identified")
	if not corrupt:
		return

	# Backfill via direct SQL (bypass doc.save() to avoid timestamp
	# races + skip the new before_save hook which would do the same
	# work per-row)
	updated = 0
	for r in corrupt:
		frappe.db.set_value("Payment Request Reference", r.name, {
			"outstanding_amount": r.grand_total,
			"base_outstanding_amount": r.base_grand_total,
		}, update_modified=False)
		updated += 1

	frappe.db.commit()
	print(f"[backfill_prf_reference_fc_amounts] updated={updated}")

	# Report which parent PRFs got touched (for audit)
	parents = sorted({r.parent for r in corrupt})
	print(f"[backfill_prf_reference_fc_amounts] affected PRFs ({len(parents)}):")
	for p in parents[:20]:
		print(f"    {p}")
	if len(parents) > 20:
		print(f"    ... and {len(parents) - 20} more")
