"""Back-fill Customer.tax_category from the company custom field on
Customer, using the SAME company→tax_category mapping defined in
`avientek.events.item.COMPANY_DEFAULTS`.

Sammish 2026-05-15. Why this exists:
  - 738 of 3073 Customers have `tax_category` blank.
  - ERPNext picks the per-item Item Tax row at SI/PO time based on the
    transaction's `tax_category` (sourced from the Customer). When that's
    blank, ERPNext silently falls back to the Item's first row → wrong
    VAT computed for FZCO / KSA / AETL / EWCIT customers.
  - Mirrors the `populate_item_defaults_for_added_companies` patch but
    on Customers instead of Items, using the SAME mapping so Items and
    Customers never drift apart.

Rules:
  - Only touches rows where `tax_category` is NULL or empty.
  - NEVER overwrites a non-blank tax_category.
  - Skips companies that have no `tax_category` in COMPANY_DEFAULTS
    (Avientek Trading W.L.L, Kenya, Singapore).
  - Uses raw UPDATE with update_modified=False so customer last-edit
    timestamps don't all jump to today.

Idempotent.
"""
import frappe

from avientek.events.item import COMPANY_DEFAULTS


def execute():
	# Build {company: tax_category} from the single source of truth.
	# Skip entries that don't define a tax_category — those customers
	# stay blank and must be set manually if needed.
	mapping = {
		entry["company"]: entry["tax_category"]
		for entry in COMPANY_DEFAULTS
		if entry.get("tax_category")
	}

	if not mapping:
		print("[populate_customer_tax_category] no mapping configured — nothing to do")
		return

	# Skip companies whose tax_category doesn't actually exist as a
	# Tax Category record — protects against typos in COMPANY_DEFAULTS.
	existing_categories = set(
		frappe.get_all("Tax Category", pluck="name")
	)
	missing = [c for c in set(mapping.values()) if c not in existing_categories]
	if missing:
		print(
			f"[populate_customer_tax_category] WARNING: these tax_category "
			f"values are not in Tax Category doctype — skipping: {missing}"
		)
		mapping = {k: v for k, v in mapping.items() if v in existing_categories}

	total_updated = 0
	per_company = {}

	for company, tax_category in mapping.items():
		# Bulk UPDATE only where tax_category is blank. update_modified=False
		# preserves the original "last modified" on Customer so we don't
		# pollute audit history for a system back-fill.
		rows = frappe.db.sql(
			"""
			UPDATE `tabCustomer`
			SET tax_category = %s
			WHERE company = %s
			  AND (tax_category IS NULL OR tax_category = '')
			""",
			(tax_category, company),
		)
		# rowcount via SHOW; safer cross-driver:
		affected = frappe.db.sql(
			"SELECT ROW_COUNT()",
		)[0][0]
		per_company[company] = (tax_category, affected)
		total_updated += affected

	frappe.db.commit()

	print("[populate_customer_tax_category] done.")
	for company, (cat, count) in per_company.items():
		print(f"  {company:60s} → {cat:20s} : {count} customers")
	print(f"  total customers updated: {total_updated}")
