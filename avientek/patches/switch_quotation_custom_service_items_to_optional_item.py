"""Switch Quotation.custom_service_items field's options to Optional Item.

Sridhar 2026-06-03: Step 4 of 'Quotation Optional Items into own
DocType' migration. After this patch runs the Quotation form's
`custom_service_items` table reads rows from `tabOptional Item`
instead of `tabQuotation Item`.

Prerequisites (already shipped in prior commits):
  - Step 1: Optional Item DocType exists
  - Step 2: 85 Custom Fields cloned onto Optional Item
  - Step 3: 19 existing custom_service_items rows already copied
    to tabOptional Item

What this patch does:
  - frappe.db.set_value on the Quotation-custom_service_items Custom
    Field: options = 'Optional Item' (was 'Quotation Item')
  - clear_cache(doctype='Quotation') so the form picks up the new
    target doctype on next render.

After this point:
  - Existing Quotations open WITHOUT data loss — the migrated rows
    on tabOptional Item are picked up by the table widget.
  - Old rows still on tabQuotation Item with parentfield=
    'custom_service_items' are now ORPHANS (not visible in the form).
    Cleanup patch (Step 8) removes them after Steps 5-7 verification.

Idempotent.
"""

import frappe


CF_NAME = "Quotation-custom_service_items"


def execute():
	if not frappe.db.exists("Custom Field", CF_NAME):
		print(f"[switch_quotation_custom_service_items_to_optional_item] {CF_NAME} missing — skipping")
		return

	current = frappe.db.get_value("Custom Field", CF_NAME, "options")
	if current == "Optional Item":
		print(f"[switch_quotation_custom_service_items_to_optional_item] already pointing at Optional Item — nothing to do")
		return

	frappe.db.set_value(
		"Custom Field", CF_NAME, "options", "Optional Item",
		update_modified=False,
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	frappe.clear_cache(doctype="Optional Item")
	frappe.clear_cache(doctype="Quotation Item")
	print(
		f"[switch_quotation_custom_service_items_to_optional_item] "
		f"options: {current!r} -> 'Optional Item'"
	)
