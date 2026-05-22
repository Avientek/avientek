"""Avientek 2026-05-13 / extended 2026-05-22 — suppress
india_compliance's "Items not covered under GST cannot be clubbed with
items for which GST is applicable" error for pre-tax-point documents.

Original case (2026-05-13, Quotation):
  Rahul/Sharavathy hit this on QN-LTD-26-01992 (Worldline Global
  Service): a mixed cart of Taxable + Non-GST items raised the
  validator and blocked save.

Extension case (2026-05-22, Purchase Order):
  Rahul Avientek hit this on POLTD26-27-00015 (Logitech Asia Pacific
  Limited, 21 mixed-GST line items) when trying to convert PO → PR.
  Same root cause — Purchase Order is the commercial agreement, not
  the tax point. Same logic extends to Purchase Receipt (goods receipt
  is not the tax event), Sales Order (commercial agreement), and
  Delivery Note (physical movement).

Where the GST clubbing rule SHOULD fire (unchanged):
  - Purchase Invoice  (inbound tax event)
  - Sales Invoice     (outbound tax event)
  These two doctypes keep their full india_compliance validation chain.

Where the clubbing rule is SUPPRESSED (this patch):
  - Quotation         (pre-sale exploratory)
  - Sales Order       (commercial agreement, pre-invoice)
  - Delivery Note     (physical movement, no tax event)
  - Purchase Order    (commercial agreement, pre-invoice)
  - Purchase Receipt  (goods receipt, no tax event)

Strategy: monkey-patch
`india_compliance.gst_india.overrides.transaction.validate_items` so
that for any of the 5 suppressed doctypes it ALWAYS runs in
`throw=False` mode. india_compliance's own `ignore_gst_validations`
then sees a False return and short-circuits the rest of
`validate_transaction` — so the clubbing error is suppressed AND the
downstream HSN / place-of-supply / GSTIN checks are also skipped for
those doctypes. That's intentional: those checks belong on the
Sales Invoice / Purchase Invoice that flows from these documents,
not on the upstream commercial paperwork itself.

The patch is installed once per Python process from a `before_validate`
doc_event on each of the 5 suppressed doctypes. Idempotent — the
second call is a no-op. File name kept as `india_gst_quotation.py`
for backward compatibility with the original 2026-05-13 hook entry
in hooks.py (function/variable names are now doctype-agnostic).
"""
import frappe


# Doctypes where the india_compliance clubbing + HSN + place-of-supply
# validation should be SUPPRESSED. These are all "pre-tax-point" docs.
# Purchase Invoice + Sales Invoice are intentionally NOT in this set.
_SUPPRESSED_DOCTYPES = frozenset({
	"Quotation",
	"Sales Order",
	"Delivery Note",
	"Purchase Order",
	"Purchase Receipt",
})


def install_patch(doc=None, method=None):
	"""Doc-event entrypoint. Hooked as `before_validate` on every
	doctype in _SUPPRESSED_DOCTYPES. Idempotently installs the
	india_compliance monkey-patch on first call. Subsequent calls
	are no-ops."""
	_install_once()


def _install_once():
	try:
		from india_compliance.gst_india.overrides import transaction as ic_tx
	except Exception:
		# india_compliance not installed — nothing to patch.
		return

	# Sentinel name kept the same so a process that already installed
	# the 2026-05-13 (Quotation-only) version replaces the closure with
	# the new multi-doctype one on the next call (only after a worker
	# restart, which Frappe Cloud Update triggers).
	if getattr(ic_tx, "_avtk_quotation_clubbing_patched", False):
		return

	original_validate_items = ic_tx.validate_items

	def patched_validate_items(doc, throw):
		"""For any doctype in _SUPPRESSED_DOCTYPES: force throw=False
		so the clubbing rule returns False instead of raising. Result:
		ignore_gst_validations returns True for that doc,
		validate_transaction exits, save succeeds. All other doctypes
		(notably Purchase Invoice + Sales Invoice — the actual tax
		points) go through unchanged."""
		if doc.doctype in _SUPPRESSED_DOCTYPES:
			return original_validate_items(doc, throw=False)
		return original_validate_items(doc, throw)

	ic_tx.validate_items = patched_validate_items
	ic_tx._avtk_quotation_clubbing_patched = True
	print(
		"[avientek.overrides.india_gst_quotation] validate_items "
		f"patched — clubbing rule suppressed for {sorted(_SUPPRESSED_DOCTYPES)}"
	)
