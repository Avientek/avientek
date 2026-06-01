"""Ensure Part Number is in every user's Quotation Report View columns.

Sridhar 2026-06-01: 'Part number also show by default Quotation report
view that is mandatory'. The previous backfill (commit 9559e76) only
inserted Quotation Item columns for users who had ZERO item columns;
users who already had SOME item columns (e.g. item_code only, no
part_number) were skipped to preserve their customization. That left
a mandatory-column gap.

This patch enforces the rule strictly: for every enabled non-admin user,
read their __UserSettings.data.Report.fields, and if
`["part_number", "Quotation Item"]` is missing, add it (right after
item_name if present, else append at the end). Same treatment for the
parent-level mirror `["first_item_part_number", "Quotation"]` —
'Item Part Number'.

Doesn't remove or reorder any other column. Idempotent.
"""

import json
import frappe


REQUIRED_FIELDS = [
	# (fieldname, parent_doctype, label_for_log)
	("first_item_part_number", "Quotation", "Item Part Number (parent)"),
	("part_number", "Quotation Item", "Part Number (item-level)"),
]


def _ensure_field(fields, fieldname, doctype):
	"""Append [fieldname, doctype] to fields if not present. Returns True if added."""
	for entry in fields:
		if isinstance(entry, list) and len(entry) >= 2 and entry[0] == fieldname and entry[1] == doctype:
			return False
	# Try inserting after item_name (Quotation Item) for the child part_number
	if doctype == "Quotation Item":
		for i, entry in enumerate(fields):
			if isinstance(entry, list) and len(entry) >= 2 and entry[0] == "item_name" and entry[1] == "Quotation Item":
				fields.insert(i + 1, [fieldname, doctype])
				return True
	# Otherwise append
	fields.append([fieldname, doctype])
	return True


def execute():
	users = frappe.db.sql_list(
		"SELECT name FROM `tabUser` WHERE enabled = 1 AND name NOT IN ('Administrator', 'Guest')"
	)

	touched = 0
	inserted = 0
	already_ok = 0

	for user in users:
		row = frappe.db.sql(
			"SELECT data FROM `__UserSettings` WHERE user = %s AND doctype = 'Quotation'",
			(user,),
		)
		if row:
			try:
				data = json.loads(row[0][0] or "{}")
			except Exception:
				data = {}
			has_row = True
		else:
			data = {}
			has_row = False

		report_cfg = data.get("Report") or {}
		fields = report_cfg.get("fields") or []

		# Always start from a fresh list to be safe
		fields = list(fields)
		any_change = False
		for fn, dt, _ in REQUIRED_FIELDS:
			if _ensure_field(fields, fn, dt):
				any_change = True

		if not any_change:
			already_ok += 1
			continue

		report_cfg["fields"] = fields
		report_cfg.setdefault("order_by", "`tabQuotation`.`modified` desc")
		report_cfg.setdefault("filters", [])
		report_cfg.setdefault("group_by", None)
		data["Report"] = report_cfg
		payload = json.dumps(data)

		if has_row:
			frappe.db.sql(
				"UPDATE `__UserSettings` SET data = %s WHERE user = %s AND doctype = 'Quotation'",
				(payload, user),
			)
			touched += 1
		else:
			frappe.db.sql(
				"INSERT INTO `__UserSettings` (user, doctype, data) VALUES (%s, %s, %s)",
				(user, "Quotation", payload),
			)
			inserted += 1

	frappe.db.commit()
	frappe.clear_cache()
	print(
		f"[enforce_part_number_in_quotation_report_view] "
		f"updated={touched} inserted={inserted} already_ok={already_ok} "
		f"total_users={len(users)}"
	)
