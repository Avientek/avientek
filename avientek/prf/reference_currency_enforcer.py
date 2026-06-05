"""Forward-enforcement hook: keep Payment Request Reference rows in
sync with their source documents' transaction-currency amounts.

Sridhar 2026-06-05 — companion to the print + report + apply-data
fixes (commits 033a05b, plus this commit). Those readers all now
prefer `grand_total` over `outstanding_amount` because historical
data on PRF reference rows has a corrupt `outstanding_amount` (AED
value stored as if it were FC) from a legacy JS mapper bug.

This hook closes the loop dynamically: whenever a PRF reference row
is saved, if it has a `reference_doctype` + `reference_name` (or
`document_reference`) AND the row's `outstanding_amount` looks like
it might be AED-equivalent (≈ base_grand_total but ≠ grand_total),
re-pull the FC value from the source doc.

The detection heuristic: if currency != company_currency AND
outstanding_amount ≈ base_grand_total but not ≈ grand_total → corrupt.

Hooked via doc_events["Payment Request Reference"]["before_save"]
and "before_insert". No-op for already-correct rows.
"""
import frappe
from frappe.utils import flt


# How close two amounts must be to count as "equal" for the heuristic.
# 0.01 catches rounding noise without false positives on legit different
# values.
TOLERANCE = 0.01


def enforce_fc_consistency(doc, method=None):
	"""If the row's outstanding_amount appears to be in company currency
	(not the row's stated currency), pull the correct FC value from
	the source doc's `outstanding_amount` field (or `grand_total` as
	fallback).
	"""
	# No-op cases
	row_currency = (doc.get("currency") or "").strip()
	if not row_currency:
		return
	company_currency = _company_currency_for_doc(doc)
	if not company_currency or row_currency == company_currency:
		# Single-currency PRF — FC == base by definition, can't be corrupt
		return

	# Without a source doc we can't re-pull anything
	ref_dt = doc.get("reference_doctype")
	ref_name = doc.get("document_reference") or doc.get("reference_name")
	if not ref_dt or not ref_name:
		return

	fc = flt(doc.get("outstanding_amount") or 0)
	base = flt(doc.get("base_outstanding_amount") or 0)
	grand = flt(doc.get("grand_total") or 0)
	base_grand = flt(doc.get("base_grand_total") or 0)

	# Skip if outstanding is empty — nothing to compare
	if not fc:
		return

	# Heuristic: if outstanding_amount matches base_grand_total but
	# differs from grand_total, the FC value has been corrupted with
	# the base (AED) value.
	corrupt_fc = (
		base_grand
		and abs(fc - base_grand) < TOLERANCE
		and grand
		and abs(fc - grand) > TOLERANCE
	)
	if not corrupt_fc:
		return  # data looks consistent

	# Re-pull from source. PI/SI: source.outstanding_amount is in FC.
	# Other doctypes: fall back to grand_total which is always FC.
	source_fc = None
	source_base = None
	if ref_dt in ("Purchase Invoice", "Sales Invoice"):
		row_data = frappe.db.get_value(ref_dt, ref_name,
			["outstanding_amount", "base_outstanding_amount"], as_dict=True)
		if row_data:
			source_fc = flt(row_data.outstanding_amount or 0)
			source_base = flt(row_data.base_outstanding_amount or 0)

	if not source_fc:
		# Fallback: use grand_total which is always FC across mappers
		source_fc = grand
		source_base = base_grand

	if source_fc and abs(source_fc - fc) > TOLERANCE:
		doc.outstanding_amount = source_fc
		if source_base:
			doc.base_outstanding_amount = source_base


def _company_currency_for_doc(doc):
	"""Walk up to the parent PRF to find company → default_currency.
	doc here is a Payment Request Reference (child row)."""
	parent = doc.get("parent")
	parenttype = doc.get("parenttype")
	if not parent or parenttype != "Payment Request Form":
		return None
	company = frappe.db.get_value("Payment Request Form", parent, "company")
	if not company:
		return None
	return frappe.db.get_value("Company", company, "default_currency")
