"""Re-sync the Avientek Number Card JSONs into existing sites.

Sridhar 2026-05-28: two Number Cards needed config changes —
- `Cancellation Requests`: was type=Custom (clicks went to bare list).
  Switched to Document Type with workflow_state IN [...] filter so the
  card navigates to the filtered Quotation list.
- `Open Sales Orders`: had a dynamic Company filter Sridhar didn't want.
  Removed dynamic_filters_json; kept the status filter (the actual pipeline).

Number Cards in our repo are fixtures imported only on fresh install.
Existing sites need a bridge patch to apply edits. This patch writes the
relevant fields directly to the existing Number Card rows (idempotent —
if the row already has the new values, no-op).
"""
import frappe


CARDS = {
	"Cancellation Requests": {
		"type": "Document Type",
		"filters_json": (
			'[["Quotation","workflow_state","in",'
			'["Cancellation Requested","Cancellation L2 Pending"]]]'
		),
		"method": "",
		"show_percentage_stats": 1,
	},
	"Open Sales Orders": {
		"dynamic_filters_json": "",
	},
}


def execute():
	for name, updates in CARDS.items():
		if not frappe.db.exists("Number Card", name):
			print(f"[resync_avientek_number_cards] {name} not present — skipping")
			continue
		current = frappe.db.get_value(
			"Number Card", name, list(updates.keys()), as_dict=True
		) or {}
		dirty = {k: v for k, v in updates.items() if (current.get(k) or "") != v}
		if not dirty:
			print(f"[resync_avientek_number_cards] {name} already up to date")
			continue
		for k, v in dirty.items():
			frappe.db.set_value("Number Card", name, k, v, update_modified=False)
		print(f"[resync_avientek_number_cards] {name} updated: {list(dirty.keys())}")

	frappe.db.commit()
	frappe.clear_cache(doctype="Number Card")
