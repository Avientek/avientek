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


def reconcile_ksa_item_tax_with_header(doc, method=None):
    """validate hook (runs after calculate_taxes_and_totals and the
    regional per-row recompute). KSA companies only; no-op elsewhere."""
    if frappe.get_cached_value("Company", doc.company, "country") != "Saudi Arabia":
        return
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
