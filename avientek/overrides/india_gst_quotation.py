"""Avientek 2026-05-13 — suppress india_compliance's
"Items not covered under GST cannot be clubbed with items for which
GST is applicable" error for Quotation only.

Rahul/Sharavathy hit this on QN-LTD-26-01992 (Worldline Global
Service): a mixed cart of Taxable + Non-GST items raised the validator
and blocked save. Quotations are PRE-SALE working documents — they
are not tax invoices, and they routinely carry exploratory mixes
(non-GST consumables next to taxable hardware). The clubbing rule
belongs to Sales Invoice / Delivery Note time, not Quotation.

Strategy: monkey-patch
`india_compliance.gst_india.overrides.transaction.validate_items` so
that when `doc.doctype == "Quotation"` it ALWAYS runs in
`throw=False` mode. india_compliance's own `ignore_gst_validations`
then sees a False return and short-circuits the rest of
`validate_transaction` — so the clubbing error is suppressed AND the
downstream HSN / place-of-supply / GSTIN checks are also skipped for
Quotations. That's intentional: those checks belong on the Sales
Invoice / Delivery Note that flows from the Quotation, not on the
exploratory quote itself.

Other sales doctypes (Sales Order, Sales Invoice, Delivery Note,
Purchase Order, etc.) keep their full india_compliance validation
chain unchanged.

The patch is installed once per Python process from a `before_validate`
doc_event on Quotation. Idempotent — the second call is a no-op.
"""
import frappe


def install_patch(doc=None, method=None):
	"""Doc-event entrypoint. Hooked as `before_validate` on Quotation.
	Idempotently installs the india_compliance monkey-patch on first
	call. Subsequent calls are no-ops."""
	_install_once()


def _install_once():
	try:
		from india_compliance.gst_india.overrides import transaction as ic_tx
	except Exception:
		# india_compliance not installed — nothing to patch.
		return

	if getattr(ic_tx, "_avtk_quotation_clubbing_patched", False):
		return

	original_validate_items = ic_tx.validate_items

	def patched_validate_items(doc, throw):
		"""For Quotation: force throw=False so the clubbing rule
		returns False instead of raising. Result: ignore_gst_validations
		returns True for that doc, validate_transaction exits, save
		succeeds. All other doctypes go through unchanged."""
		if doc.doctype == "Quotation":
			return original_validate_items(doc, throw=False)
		return original_validate_items(doc, throw)

	ic_tx.validate_items = patched_validate_items
	ic_tx._avtk_quotation_clubbing_patched = True
	print("[avientek.overrides.india_gst_quotation] validate_items patched — Quotation clubbing rule suppressed")
