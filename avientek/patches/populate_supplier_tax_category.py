"""Back-fill Supplier.tax_category — CONSERVATIVE variant.

Sammish 2026-05-15. Unlike Customer, Supplier.company tells us "which
Avientek entity buys from this supplier", NOT "where the supplier is
based". A foreign vendor we import from via Avientek FZCO has
company=Avientek FZCO but their correct tax_category is "Overseas"
(zero-rated import), not "FREE ZONE".

To avoid silently mis-tagging import suppliers as domestic and
charging 5% VAT on zero-rated imports, this patch only fills the
ONE company where domestic-vs-overseas is unambiguous:

  Avientek Electronics Trading PVT. LTD (India)  →  Registered Regular

All other companies (FZCO / AETL / KSA / EWCIT / ATW / AK / AETPLS /
AG) are SKIPPED — those suppliers must be classified manually per
supplier (some are domestic Mainland/FreeZone, some are Overseas
imports, and the data on prod doesn't let us tell them apart safely).

Idempotent. Only fills blanks. Never overwrites.
"""
import frappe


# Companies where we can SAFELY default the tax_category without
# risk of mis-tagging Overseas/import suppliers. Add to this dict
# only when you're confident every supplier on that company is
# domestic, never an import vendor.
SAFE_COMPANY_TO_CATEGORY = {
	"Avientek Electronics Trading PVT. LTD": "Registered Regular",
}


def execute():
	# Verify each target tax_category actually exists.
	existing = set(frappe.get_all("Tax Category", pluck="name"))
	mapping = {
		co: cat for co, cat in SAFE_COMPANY_TO_CATEGORY.items()
		if cat in existing
	}
	missing = [c for c in SAFE_COMPANY_TO_CATEGORY.values() if c not in existing]
	if missing:
		print(
			f"[populate_supplier_tax_category] WARNING: skipping unknown "
			f"Tax Category entries: {missing}"
		)
	if not mapping:
		print("[populate_supplier_tax_category] nothing safe to fill — done")
		return

	total = 0
	for company, tax_category in mapping.items():
		frappe.db.sql(
			"""
			UPDATE `tabSupplier`
			SET tax_category = %s
			WHERE company = %s
			  AND (tax_category IS NULL OR tax_category = '')
			""",
			(tax_category, company),
		)
		affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0]
		total += affected
		print(f"  {company:60s} → {tax_category:20s} : {affected} suppliers")

	frappe.db.commit()
	print(
		f"[populate_supplier_tax_category] done. total suppliers updated: {total}"
	)
