"""Drop parent comma-joined Part Number mirrors from Report View defaults
and position the per-item Part Number column right after Item Code.

Sridhar 2026-06-01: 'why comma for part number and showing ? no need that'.
The parent-level Quotation.first_item_part_number / .optional_item_part_numbers
were exposed in default Report View columns to surface Part Numbers
quickly, but they render as comma-joined lists ("1208671, 1208672, ...")
and repeat the SAME value across every item-level row of the same
quote — confusing and redundant once the per-item Quotation Item
.part_number is also shown.

This patch:
  1. Sets in_list_view = 0 on both parent mirror Custom Fields so they
     stop appearing in default column lists for any new user.
  2. For every existing user's __UserSettings.data.Report.fields:
       - REMOVE ["first_item_part_number", "Quotation"] if present
       - REMOVE ["optional_item_part_numbers", "Quotation"] if present
       - MOVE ["part_number", "Quotation Item"] to immediately after
         ["item_code", "Quotation Item"] (insert if missing)
  3. The parent Custom Fields themselves remain in the schema (hooks
     keep them in sync) — only their default Report View visibility
     and order is corrected.

Idempotent.
"""

import json
import frappe


PARENT_FIELDS_TO_REMOVE = [
	["first_item_part_number", "Quotation"],
	["optional_item_part_numbers", "Quotation"],
]


def execute():
	# 1. Stop auto-including the parent mirrors in default column lists
	for cf_name in ("Quotation-first_item_part_number", "Quotation-optional_item_part_numbers"):
		if frappe.db.exists("Custom Field", cf_name):
			frappe.db.set_value(
				"Custom Field", cf_name,
				{"in_list_view": 0},
				update_modified=False,
			)

	# 2. Rewrite each user's saved Report config
	users = frappe.db.sql_list(
		"SELECT name FROM `tabUser` WHERE enabled = 1 AND name != 'Guest'"
	)

	touched = 0
	for user in users:
		row = frappe.db.sql(
			"SELECT data FROM `__UserSettings` WHERE user = %s AND doctype = 'Quotation'",
			(user,),
		)
		if not row:
			continue
		try:
			data = json.loads(row[0][0] or "{}")
		except Exception:
			continue

		rcfg = data.get("Report") or {}
		fields = list(rcfg.get("fields") or [])
		if not fields:
			continue

		original = list(fields)

		# Drop parent mirror entries
		fields = [
			e for e in fields
			if not (isinstance(e, list) and len(e) >= 2 and [e[0], e[1]] in PARENT_FIELDS_TO_REMOVE)
		]

		# Locate item_code (Quotation Item) and part_number (Quotation Item)
		item_code_idx = None
		part_number_idx = None
		for i, e in enumerate(fields):
			if isinstance(e, list) and len(e) >= 2 and e[1] == "Quotation Item":
				if e[0] == "item_code" and item_code_idx is None:
					item_code_idx = i
				elif e[0] == "part_number" and part_number_idx is None:
					part_number_idx = i

		part_entry = ["part_number", "Quotation Item"]
		if item_code_idx is not None:
			# Remove existing part_number (if anywhere)
			if part_number_idx is not None:
				fields.pop(part_number_idx)
				# item_code_idx may shift if part_number was before it
				if part_number_idx < item_code_idx:
					item_code_idx -= 1
			# Insert right after item_code
			fields.insert(item_code_idx + 1, part_entry)
		else:
			# No item_code in user's config — leave part_number where it
			# is (or skip), don't force-add item_code here.
			pass

		if fields == original:
			continue

		rcfg["fields"] = fields
		data["Report"] = rcfg
		frappe.db.sql(
			"UPDATE `__UserSettings` SET data = %s WHERE user = %s AND doctype = 'Quotation'",
			(json.dumps(data), user),
		)
		# Invalidate Frappe's per-user Redis cache (it shadows __UserSettings
		# on read — without this, browsers serve stale columns until the
		# cache TTL expires or sync_user_settings runs).
		frappe.cache.hdel("_user_settings", f"Quotation::{user}")
		touched += 1

	frappe.db.commit()
	frappe.clear_cache()
	print(f"[fix_quotation_report_part_number_layout] user settings rewritten: {touched}")
