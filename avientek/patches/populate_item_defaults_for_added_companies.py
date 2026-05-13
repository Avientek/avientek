"""Back-fill Item Defaults + Item Tax Templates for the 3 companies that
were missing from the original populate_item_defaults_and_taxes patch:

  - AVIENTEK TRADING LLC                       (abbr=KSA)
  - Avientek Electronics Trading Private Limited (abbr=AETPLS)
  - Avientek Group                              (abbr=AG)

Sammish 2026-05-15. Root cause: PO/PR created on AVIENTEK TRADING LLC
fell back to UAE VAT 5% - A as the per-item tax template because the
item's tax table had no entry ending in " - KSA". ERPNext then computed
VAT 15% as 0% because the UAE template has no row for the "VAT 15% - KSA"
account.

Idempotent. Only adds rows that are MISSING — never overwrites.

The after-save hook (`avientek.events.item.auto_populate_defaults`)
already handles future saves automatically; this patch fills in
existing items that haven't been edited since the new companies were
added.
"""
import frappe

from avientek.events.item import COMPANY_DEFAULTS


def execute():
	items = frappe.get_all("Item", pluck="name")
	total = len(items)
	updated = 0
	added_tax_rows = 0
	added_default_rows = 0

	for idx, item_name in enumerate(items):
		try:
			doc = frappe.get_doc("Item", item_name)
		except Exception:
			continue

		existing_companies = {d.company for d in doc.get("item_defaults", []) if d.company}
		# Index existing Item Tax rows by template so we can detect both
		# "missing row" AND "row exists but tax_category is blank".
		tax_rows_by_template = {t.item_tax_template: t for t in doc.get("taxes", []) if t.item_tax_template}

		changed = False
		for entry in COMPANY_DEFAULTS:
			if entry["company"] not in existing_companies:
				row = {"company": entry["company"]}
				if entry.get("income_account"):
					row["income_account"] = entry["income_account"]
				doc.append("item_defaults", row)
				added_default_rows += 1
				changed = True

			tpl = entry.get("tax_template")
			if not tpl:
				continue
			cat = entry.get("tax_category")
			if tpl not in tax_rows_by_template:
				tax_row = {"item_tax_template": tpl}
				if cat:
					tax_row["tax_category"] = cat
				doc.append("taxes", tax_row)
				added_tax_rows += 1
				changed = True
			elif cat and not getattr(tax_rows_by_template[tpl], "tax_category", None):
				# Row exists but tax_category is blank — back-fill it.
				tax_rows_by_template[tpl].tax_category = cat
				changed = True

		if changed:
			doc.flags.ignore_validate = True
			doc.flags.ignore_mandatory = True
			doc.flags.ignore_permissions = True
			# Suppress the same auto_populate_defaults hook to avoid
			# duplicate work in the same save cycle. The before_save
			# hook is idempotent, but skipping it speeds the bulk run.
			doc.flags.in_avientek_company_backfill = True
			try:
				doc.save()
				updated += 1
			except Exception:
				frappe.log_error(
					title=f"populate_item_defaults_for_added_companies: save failed for {item_name}",
					message=frappe.get_traceback(),
				)

		if (idx + 1) % 500 == 0:
			frappe.db.commit()
			print(f"Processed {idx + 1}/{total} items, updated {updated}")

	frappe.db.commit()
	print(
		f"[populate_item_defaults_for_added_companies] done. "
		f"items_total={total} items_updated={updated} "
		f"item_defaults_added={added_default_rows} item_tax_rows_added={added_tax_rows}"
	)
