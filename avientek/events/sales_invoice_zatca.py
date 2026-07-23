"""KSA / ZATCA helpers for Sales Invoice.

Rahul via Sammish 2026-07-23 (INV-AT-26-00369): ZATCA rejected a KSA
invoice with BR-CO-14 ("Invoice total VAT (BT-110) = Σ VAT category tax
(BT-117)") and BR-CO-15 (gross = net + VAT).

Root cause — a rounding-drift class, not bad data:

* ERPNext computes the HEADER VAT once, on the net total
  (11,535.24 x 15% = 1,730.29 on the reported invoice).
* ERPNext's Saudi regional override (`regional_overrides` →
  `united_arab_emirates.utils.update_itemised_tax_data`) then recomputes
  each ROW's `tax_amount` independently as `net_amount x rate`, rounded
  per row. Those per-row roundings summed to 1,730.30-.31.
* ksa_compliance builds the ZATCA XML's line and VAT-category totals
  from the per-row `tax_amount`s, while BT-110 comes from the header —
  so any invoice whose per-row roundings drift ≥ ~2 fils from the
  header fails ZATCA validation and cannot be submitted.

Free-of-charge lines (rate 0, business-required — Avientek bundles free
items) made it worse: on ERPNext v15 the per-item tax map is keyed by
ITEM CODE, so a free line repeating a priced line's item code shares its
tax bucket and can pick up a stray fils (the reported invoice's zero
line carried 0.01 in the generated XML). ksa_compliance's own source
documents the duplicate-item-code limitation on v15; their fix requires
ERPNext v16's row-keyed Item Wise Tax Detail table.

Fix here: after ERPNext's recompute, reconcile the per-row tax amounts
so they sum EXACTLY to the header VAT. The ±fils residue lands on the
largest taxed row (standard e-invoicing practice — one line absorbs the
rounding, totals stay authoritative). Zero-net (free) rows are never
touched, and their business representation is preserved as-is.
"""

import frappe
from frappe.utils import flt

# Residue beyond this is NOT rounding drift — something is genuinely
# wrong with the tax setup, and hiding it would falsify the invoice.
_MAX_RECONCILE = 0.05


_ksa_patch_applied = False


def _ensure_ksa_patch():
    """Apply the ksa_compliance XML monkey-patch once, lazily. Called from
    the SI validate hook — by then ksa_compliance is fully imported, so
    there's no circular import (which is why this can't live in
    avientek/__init__.py at app-load time)."""
    global _ksa_patch_applied
    if _ksa_patch_applied:
        return
    try:
        patch_ksa_einvoice_tax_reconciliation()
        _ksa_patch_applied = True
    except Exception:
        frappe.log_error(
            title="KSA e-invoice reconciliation patch failed to apply",
            message=frappe.get_traceback(),
        )


def reconcile_ksa_item_tax_with_header(doc, method=None):
    """validate hook (runs after calculate_taxes_and_totals and the
    regional per-row recompute). KSA companies only; no-op elsewhere."""
    if frappe.get_cached_value("Company", doc.company, "country") != "Saudi Arabia":
        return
    # Ensure the ksa XML builder is patched before this doc reaches
    # on_submit (same request, so the patch is live by then).
    _ensure_ksa_patch()
    if not doc.get("taxes") or not doc.get("items"):
        return
    if not doc.items[0].meta.has_field("tax_amount"):
        return  # regional custom fields absent — nothing to reconcile

    header_vat = flt(doc.total_taxes_and_charges, 2)
    line_sum = flt(sum(flt(row.tax_amount) for row in doc.items), 2)
    residue = flt(header_vat - line_sum, 2)
    if not residue:
        return
    if abs(residue) > _MAX_RECONCILE:
        return  # not fils-drift — leave it visible for ZATCA to reject

    # Largest taxed row absorbs the residue. Never a zero-net (free) row:
    # a free line must stay 0.00 in the XML.
    target = None
    for row in doc.items:
        if flt(row.net_amount) <= 0:
            continue
        if target is None or flt(row.tax_amount) > flt(target.tax_amount):
            target = row
    if target is None:
        return

    target.tax_amount = flt(flt(target.tax_amount) + residue, 2)
    if target.meta.has_field("total_amount"):
        target.total_amount = flt(flt(target.net_amount) + flt(target.tax_amount), 2)


def patch_ksa_einvoice_tax_reconciliation():
    """Monkey-patch ksa_compliance's e-invoice line builder so the ZATCA
    XML's per-line / VAT-category tax (BT-117) sums EXACTLY to the header
    VAT (BT-110). Applied at app load from avientek/__init__.py.

    Why the validate hook above isn't enough: ksa_compliance builds the
    ZATCA XML in on_submit, from a FRESHLY reloaded Sales Invoice
    (`frappe.get_doc` in SalesInvoiceAdditionalFields.before_insert →
    Einvoice), so any in-memory reconciliation done during validate is
    gone by the time the XML is produced.

    The drift is round-then-sum vs sum-then-round: ERPNext derives BT-110
    by rounding the total once (net_total x rate), while ksa's XML rounds
    each line's tax then sums. When several lines carry a .5-fils third
    decimal (e.g. 631.845, 676.656, 14.928) the per-line roundings push
    the category total 1-2 fils above BT-110 and ZATCA rejects with
    BR-CO-14 / BR-CO-15. Duplicate item codes on free (rate-0) lines make
    it worse on ksa's v15 code path, dumping a stray fils on a zero line.

    Fix: after ksa builds `item_lines`, nudge the per-line tax_amounts so
    they sum to the header VAT, residue onto the largest taxed line;
    zero-net (free) lines are never touched. Same policy as the validate
    hook, applied where it actually reaches the XML.
    """
    from ksa_compliance.output_models import e_invoice_output_model as _m

    _original = _m.Einvoice._append_sales_invoice_items

    def _patched(self, item_lines, is_tax_included, doc):
        _original(self, item_lines, is_tax_included, doc)
        try:
            _reconcile_item_lines_to_header(item_lines, doc)
        except Exception:
            frappe.log_error(
                title="KSA e-invoice tax reconciliation skipped",
                message=frappe.get_traceback(),
            )

    _m.Einvoice._append_sales_invoice_items = _patched


def _reconcile_item_lines_to_header(item_lines, doc):
    if getattr(doc, "doctype", None) != "Sales Invoice":
        return
    header_vat = flt(doc.get("total_taxes_and_charges"), 2)
    if not header_vat:
        return
    line_sum = flt(sum(flt(il.get("tax_amount")) for il in item_lines), 2)
    residue = flt(header_vat - line_sum, 2)
    if not residue or abs(residue) > _MAX_RECONCILE:
        return

    target = None
    for il in item_lines:
        if flt(il.get("net_amount")) <= 0:
            continue
        if target is None or flt(il.get("tax_amount")) > flt(target.get("tax_amount")):
            target = il
    if target is None:
        return

    target.tax_amount = flt(flt(target.get("tax_amount")) + residue, 2)
    # rounding_amount = tax_amount + amount (see the builder); keep consistent
    if "rounding_amount" in target:
        target.rounding_amount = flt(flt(target.get("amount")) + flt(target.tax_amount), 2)
