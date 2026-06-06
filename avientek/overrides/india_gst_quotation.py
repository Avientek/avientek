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

	# Sentinel bumped to v3 (Sridhar 2026-06-05, 2nd iteration):
	# v1 (2026-05-13) required `throw` as a positional arg with no
	#   default. Broke when a caller stopped passing it.
	# v2 (earlier today) made `throw=True` default + **kwargs to
	#   absorb extras — but ALSO forwarded `throw=False` to the
	#   original. That broke on Frappe Cloud's NEW india_compliance
	#   where the upstream `validate_items(doc)` signature DROPPED
	#   the throw parameter entirely:
	#     TypeError: validate_items() got an unexpected keyword
	#     argument 'throw'
	# v3: introspect upstream signature once at install time and
	#   adapt the delegation call. Works against both old IC (which
	#   expects `validate_items(doc, throw)`) and new IC (just
	#   `validate_items(doc)`).
	if getattr(ic_tx, "_avtk_quotation_clubbing_patched_v3", False):
		return

	original_validate_items = ic_tx.validate_items

	# Inspect the upstream signature ONCE so we know whether to
	# forward `throw` to it. Defaults to "no throw" on inspect
	# failure since the newer IC is the more common case post-upgrade.
	import inspect
	_orig_accepts_throw = False
	try:
		_orig_sig = inspect.signature(original_validate_items)
		_orig_accepts_throw = "throw" in _orig_sig.parameters
	except (TypeError, ValueError):
		_orig_accepts_throw = False

	def patched_validate_items(doc, *args, **kwargs):
		"""Multi-version-safe patch for india_compliance's validate_items.

		Two upstream signatures exist in the wild:
		  OLD: validate_items(doc, throw)         (throw positional)
		  NEW: validate_items(doc)                (throw removed)

		We absorb whatever the CALLER passes (any signature) via
		`*args, **kwargs`, and we forward to the ORIGINAL using the
		signature we detected at install time.

		For doctypes in _SUPPRESSED_DOCTYPES (Quotation, SO, DN, PO,
		PR, PI — everything except Sales Invoice, the actual tax
		point), we return False directly without invoking the
		original. That causes ignore_gst_validations to short-circuit
		to True → validate_transaction exits → save succeeds. Skipping
		the upstream call is also necessary because on the NEW
		signature there's no `throw=False` knob to suppress raising.

		For all other doctypes (notably Sales Invoice), forward to the
		original. If the original accepts `throw`, pass either the
		caller-provided value or default True. If not, just pass doc.
		"""
		if doc.doctype in _SUPPRESSED_DOCTYPES:
			return False

		if _orig_accepts_throw:
			# Forward throw from caller if they gave one, else
			# default True (matches the old upstream default).
			throw_val = (
				args[0] if args
				else kwargs.get("throw", True)
			)
			return original_validate_items(doc, throw_val)

		# New upstream: signature is just (doc). Drop any extras
		# the caller may have passed.
		return original_validate_items(doc)

	ic_tx.validate_items = patched_validate_items
	# Keep older-version sentinels set so any code path checking them
	# doesn't re-patch over us.
	ic_tx._avtk_quotation_clubbing_patched = True
	ic_tx._avtk_quotation_clubbing_patched_v2 = True
	ic_tx._avtk_quotation_clubbing_patched_v3 = True
	print(
		"[avientek.overrides.india_gst_quotation] validate_items "
		f"patched v3 — upstream accepts throw: {_orig_accepts_throw}; "
		f"clubbing rule suppressed for {sorted(_SUPPRESSED_DOCTYPES)}"
	)
