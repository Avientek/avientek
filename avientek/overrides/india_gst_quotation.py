"""Avientek 2026-05-13 / extended 2026-05-22 (twice) — suppress
india_compliance's "Items not covered under GST cannot be clubbed with
items for which GST is applicable" error for pre-tax-point documents.

Original case (2026-05-13, Quotation):
  Rahul/Sharavathy hit this on QN-LTD-26-01992 (Worldline Global
  Service): a mixed cart of Taxable + Non-GST items raised the
  validator and blocked save.

First extension case (2026-05-22 AM, Purchase Order / Purchase Receipt):
  Rahul Avientek hit this on POLTD26-27-00015 (Logitech Asia Pacific
  Limited, 21 mixed-GST line items) when trying to convert PO → PR.
  Same root cause — Purchase Order is the commercial agreement, not
  the tax point. Same logic extends to Purchase Receipt (goods receipt
  is not the tax event), Sales Order (commercial agreement), and
  Delivery Note (physical movement).

Second extension case (2026-05-22 PM, Purchase Invoice — GRN717):
  Rahul + Jithin: "GRN issue is solved, but while converting then GRN
  to Purchase Invoice, the issue still exist. We must take inward and
  process a payment to supplier — all stuck." The original design left
  PI as the inbound tax point, but the natural workflow PO → PR → PI
  carries forward the SAME mixed-item bundle that was already approved
  upstream. Forcing users to manually split into two PIs blocks billing
  for legitimate documents that already cleared PO + GRN. Each line
  retains its own GST treatment / tax_category, so the GST returns
  still bucket items correctly per HSN.

Where the GST clubbing rule SHOULD fire (unchanged):
  - Sales Invoice     (outbound tax event — customer-facing, splitting
                       there is straightforward at quote→SI conversion)
  Sales Invoice keeps its full india_compliance validation chain.

Where the clubbing rule is SUPPRESSED (this patch):
  - Quotation         (pre-sale exploratory)
  - Sales Order       (commercial agreement, pre-invoice)
  - Delivery Note     (physical movement, no tax event)
  - Purchase Order    (commercial agreement, pre-invoice)
  - Purchase Receipt  (goods receipt, no tax event)
  - Purchase Invoice  (allows mixed inward bundles from PR — tax
                       bucketing still happens per line via tax_category)

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
# validation should be SUPPRESSED. Sales Invoice intentionally remains
# OUTSIDE this set — outbound tax compliance is enforced there.
_SUPPRESSED_DOCTYPES = frozenset({
	"Quotation",
	"Sales Order",
	"Delivery Note",
	"Purchase Order",
	"Purchase Receipt",
	"Purchase Invoice",
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

	# Sentinel bumped to v2 for ERP-TKT (Sridhar 2026-06-05): the
	# 2026-05-13 patched_validate_items required `throw` as a positional
	# arg with no default. After the india_compliance / ERPNext upgrade
	# on Frappe Cloud, at least one caller now invokes validate_items
	# WITHOUT `throw`, so Purchase Receipt save crashed with
	#   TypeError: _install_once..patched_validate_items() missing 1
	#   required positional argument: 'throw'
	# Bumping the sentinel name forces workers that already loaded the
	# v1 closure to install the new (`throw=True` default + **kwargs)
	# version on the next before_validate without needing a full
	# worker restart.
	if getattr(ic_tx, "_avtk_quotation_clubbing_patched_v2", False):
		return

	original_validate_items = ic_tx.validate_items

	def patched_validate_items(doc, throw=True, *args, **kwargs):
		"""For any doctype in _SUPPRESSED_DOCTYPES: force throw=False
		so the clubbing rule returns False instead of raising. Result:
		ignore_gst_validations returns True for that doc,
		validate_transaction exits, save succeeds. All other doctypes
		(notably Sales Invoice — the actual tax point) go through
		unchanged.

		`throw` defaults to True (matches the upstream
		`ignore_gst_validations(doc, throw=True)` default) so callers
		that pass only `doc` don't crash. `*args, **kwargs` absorb any
		additional params a future india_compliance upgrade may add."""
		if doc.doctype in _SUPPRESSED_DOCTYPES:
			return original_validate_items(doc, throw=False)
		return original_validate_items(doc, throw, *args, **kwargs)

	ic_tx.validate_items = patched_validate_items
	# Keep the v1 sentinel set so we don't accidentally re-patch via the
	# old name elsewhere, then set v2 as the live sentinel.
	ic_tx._avtk_quotation_clubbing_patched = True
	ic_tx._avtk_quotation_clubbing_patched_v2 = True
	print(
		"[avientek.overrides.india_gst_quotation] validate_items "
		f"patched v2 — clubbing rule suppressed for {sorted(_SUPPRESSED_DOCTYPES)}"
	)
