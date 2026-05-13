import frappe

# Sammish 2026-05-15: source of truth moved to avientek.events.item.COMPANY_DEFAULTS
# so the after-save hook and the bulk patch never drift apart. This patch keeps
# its own import-time alias so callers can still reference COMPANY_DEFAULTS here.
from avientek.events.item import COMPANY_DEFAULTS  # noqa: E402,F401


def execute():
	"""Bulk populate Item Defaults and Item Tax Templates for all existing items."""
	items = frappe.get_all("Item", pluck="name")
	total = len(items)
	updated = 0

	for idx, item_name in enumerate(items):
		doc = frappe.get_doc("Item", item_name)
		existing_companies = {d.company for d in doc.get("item_defaults", [])}
		existing_templates = {t.item_tax_template for t in doc.get("taxes", [])}

		changed = False

		for entry in COMPANY_DEFAULTS:
			if entry["company"] not in existing_companies:
				row = {"company": entry["company"]}
				if entry.get("income_account"):
					row["income_account"] = entry["income_account"]
				doc.append("item_defaults", row)
				changed = True

			if entry.get("tax_template") and entry["tax_template"] not in existing_templates:
				doc.append("taxes", {"item_tax_template": entry["tax_template"]})
				changed = True

		if changed:
			doc.flags.ignore_validate = True
			doc.flags.ignore_mandatory = True
			doc.flags.ignore_permissions = True
			doc.save()
			updated += 1

		if (idx + 1) % 500 == 0:
			frappe.db.commit()
			print(f"Processed {idx + 1}/{total} items, updated {updated}")

	frappe.db.commit()
	print(f"Done. Updated {updated}/{total} items.")
