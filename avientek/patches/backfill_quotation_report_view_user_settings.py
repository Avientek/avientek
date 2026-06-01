"""Backfill per-user Report View settings on Quotation so every user lands
on the item-level expanded view by default — matching how Sales Order
already works (each user has child-table columns saved in __UserSettings,
which is why SO Report View shows multiple rows per order).

Sridhar 2026-06-01: 'the SO working the same way should work Quotation
report view'. SO Report View shows item-level rows because EACH user's
__UserSettings.data has Sales Order Item columns saved. For Quotation,
50+ users don't have those settings yet → they see parent-only rows.

This patch:
  1. For each existing enabled User, read their __UserSettings.data for
     doctype='Quotation'.
  2. If the Report section is missing OR has zero Quotation Item child
     columns, REPLACE the Report.fields with the standard item-level
     column set (same one used in the saved 'Quotation Item Detail'
     report).
  3. Leave users alone whose Quotation Report config already has any
     Quotation Item field — preserves customization.

Idempotent. After this runs, every user opens /app/quotation/view/report
and sees item-level expanded rows out of the box.
"""

import json
import frappe


STANDARD_FIELDS = [
	# Parent
	["name", "Quotation"],
	["workflow_state", "Quotation"],
	["status", "Quotation"],
	["transaction_date", "Quotation"],
	["customer", "Quotation"],
	["customer_name", "Quotation"],
	["company", "Quotation"],
	["currency", "Quotation"],
	["grand_total", "Quotation"],
	["base_grand_total", "Quotation"],
	# Child (drives row expansion)
	["item_code", "Quotation Item"],
	["item_name", "Quotation Item"],
	["part_number", "Quotation Item"],
	["qty", "Quotation Item"],
	["rate", "Quotation Item"],
	["amount", "Quotation Item"],
	["net_rate", "Quotation Item"],
	["net_amount", "Quotation Item"],
	["base_amount", "Quotation Item"],
	["base_net_amount", "Quotation Item"],
	["warehouse", "Quotation Item"],
	["brand", "Quotation Item"],
]


def _has_quotation_item_field(report_cfg):
	if not isinstance(report_cfg, dict):
		return False
	fields = report_cfg.get("fields") or []
	for entry in fields:
		if isinstance(entry, list) and len(entry) >= 2 and entry[1] == "Quotation Item":
			return True
	return False


def execute():
	# Include Administrator (commonly used for testing). Guest excluded
	# since it has no UI session.
	users = frappe.db.sql_list(
		"SELECT name FROM `tabUser` WHERE enabled = 1 AND name != 'Guest'"
	)

	updated = 0
	inserted = 0
	preserved = 0

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
		else:
			data = {}

		report_cfg = data.get("Report") or {}
		if _has_quotation_item_field(report_cfg):
			preserved += 1
			continue

		# Write the standard column set, preserving any existing filters / sort.
		report_cfg["fields"] = STANDARD_FIELDS
		report_cfg.setdefault("order_by", "`tabQuotation`.`modified` desc")
		report_cfg.setdefault("filters", [])
		report_cfg.setdefault("group_by", None)
		report_cfg.setdefault("add_totals_row", 0)
		data["Report"] = report_cfg

		if row:
			frappe.db.sql(
				"UPDATE `__UserSettings` SET data = %s WHERE user = %s AND doctype = 'Quotation'",
				(json.dumps(data), user),
			)
			updated += 1
		else:
			frappe.db.sql(
				"INSERT INTO `__UserSettings` (user, doctype, data) VALUES (%s, %s, %s)",
				(user, "Quotation", json.dumps(data)),
			)
			inserted += 1

	frappe.db.commit()
	frappe.clear_cache()
	print(
		f"[backfill_quotation_report_view_user_settings] "
		f"updated={updated} inserted={inserted} preserved={preserved} "
		f"total_users={len(users)}"
	)
