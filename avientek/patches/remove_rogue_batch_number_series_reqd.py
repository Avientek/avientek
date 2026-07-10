"""Delete the rogue Item-batch_number_series-reqd Property Setter.

Sridhar 2026-07-09: reported HSN/SAC-adjacent bug — "Batch Number Series
is required" blocked saving a plain Item with no batch settings at all.

Root cause: a Property Setter (Item-batch_number_series-reqd, value=1,
is_system_generated=0) forces this field mandatory on EVERY Item,
unconditionally. Core ERPNext's own definition of this field
(erpnext/stock/doctype/item/item.json) has no reqd at all — it only has
depends_on: eval:doc.has_batch_no==1 && doc.create_new_batch==1, i.e. the
field is meant to be relevant (let alone required) only when both those
checkboxes are set. is_system_generated=0 means this was created by hand
via Customize Form at some point, not shipped by any app/patch — not
tracked in this repo's fixtures at all (confirmed by search), same
"unowned override" pattern as the custom_quote_project field
(purge_custom_quote_project_field.py).

Safe to delete outright (not blank, unlike the HSN case): core's own
field definition has no reqd baked in underneath, so deleting this
restores the true default (optional) rather than exposing anything
broken.

Idempotent — re-running is a no-op once deleted. One-shot only; add an
after_migrate recurring purge (see migrate.py) if this turns out to keep
reappearing, same as custom_quote_project did.
"""

import frappe


PROPERTY_SETTER = "Item-batch_number_series-reqd"


def execute():
	if not frappe.db.exists("Property Setter", PROPERTY_SETTER):
		print(f"[remove_rogue_batch_number_series_reqd] {PROPERTY_SETTER} not present — already clean")
		return

	frappe.delete_doc("Property Setter", PROPERTY_SETTER, ignore_permissions=True, force=True)
	frappe.db.commit()
	frappe.clear_cache(doctype="Item")
	print(f"[remove_rogue_batch_number_series_reqd] Deleted {PROPERTY_SETTER}")
