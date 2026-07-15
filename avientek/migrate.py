from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def _run_step(label, fn):
	"""Run one after_migrate step in isolation. A failure in one step must NOT
	abort the rest — before this guard, an early step raising (e.g. during a
	Frappe Cloud deploy) skipped everything after it, including
	_unblock_avientek_module, so GM-CS users lost the Sales Team workspace +
	number cards (prod 2026-07-08). Each step commits on success; on failure it
	rolls back its own partial work, logs, and we continue."""
	try:
		fn()
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(
			title=f"after_migrate step failed: {label}",
			message=frappe.get_traceback(),
		)
		print(f"[after_migrate] step {label!r} FAILED (continuing) — see Error Log")


def after_migrate():
	# Jithin 2026-05-15 — default PRF print format = "Payment Voucher Fast".
	# Idempotent via make_property_setter.
	steps = [
		("item_search_fields", lambda: make_property_setter(
			"Item", None, "search_fields",
			"item_name,description,item_group,customer_code,part_number",
			"Data", for_doctype="Doctype")),
		("prf_default_print_format", lambda: make_property_setter(
			"Payment Request Form", None, "default_print_format",
			"Payment Voucher Fast", "Data", for_doctype="Doctype")),
		("create_asset_dam_fields", _create_asset_dam_fields),
		("deactivate_old_quotation_workflows", _deactivate_old_quotation_workflows),
		("fix_quotation_item_calc_layout", _fix_quotation_item_calc_layout),
		("fix_global_field_settings", _fix_global_field_settings),
		("enforce_custom_role_permissions", _enforce_custom_role_permissions),
		("enforce_export_permissions", _enforce_export_permissions),
		("sync_payment_voucher_formats", _sync_payment_voucher_formats),
		("sync_sales_team_workspace", _sync_sales_team_workspace),
		("unblock_avientek_module", _unblock_avientek_module),
		("seed_quotation_approval_v3_workflow", _seed_quotation_approval_v3_workflow),
		("purge_custom_quote_project_field", _purge_custom_quote_project_field),
	]
	for label, fn in steps:
		_run_step(label, fn)


def _unblock_avientek_module():
	"""Keep the Avientek + Avientek Reports modules UNblocked on every Module
	Profile AND User, every migrate.

	Frappe v15's desk sidebar hides a workspace whose `module` is blocked for
	the user. The Sales Team workspace is module=Avientek, so a GM-CS / CS user
	whose Module Profile blocks 'Avientek' can't see it even with the right
	roles + read perms (Jithin 2026-05-19: Rahul; Sridhar 2026-07-06:
	st@/Shijin Thomas). The one-time `unblock_avientek_module_for_module_profiles`
	patch fixes it once, but does NOT re-apply if a profile/user gets re-blocked
	later — so we re-assert it here idempotently (same pattern as the workspace
	sync + workflow re-seed).

	Cleans BOTH the Module Profile rows AND any direct User-level block rows,
	then re-saves affected users so their cached block_modules table syncs.
	No-op (a cheap scan) when nothing is blocked.
	"""
	UNBLOCK = ("Avientek", "Avientek Reports")
	rows = frappe.db.get_all(
		"Block Module",
		filters={
			"module": ["in", UNBLOCK],
			"parenttype": ["in", ("Module Profile", "User")],
		},
		fields=["parent", "parenttype"],
	)
	if not rows:
		return

	profiles = {r.parent for r in rows if r.parenttype == "Module Profile"}
	users = {r.parent for r in rows if r.parenttype == "User"}

	# Drop the block rows at both levels in one shot.
	frappe.db.delete("Block Module", {
		"module": ["in", UNBLOCK],
		"parenttype": ["in", ("Module Profile", "User")],
	})

	# Users inheriting a now-cleaned profile also need their cached table synced.
	if profiles:
		for u in frappe.db.get_all(
			"User",
			filters={"module_profile": ["in", list(profiles)], "enabled": 1},
			pluck="name",
		):
			users.add(u)

	frappe.db.commit()

	# NOTE: Administrator's cache MUST be cleared when it was the blocked party.
	# Frappe filters Number Card / Dashboard Chart visibility by
	# get_modules_from_all_apps_for_user(), which subtracts *Administrator's*
	# blocked modules GLOBALLY for every user (frappe/config/__init__.py) — on
	# top of the per-user list. So a stale cached Administrator doc with Avientek
	# still blocked hides all module=Avientek number cards for EVERY user, even
	# though the workspace itself (filtered only by the user's own block list)
	# still renders. This exact mismatch caused a long prod hunt on 2026-07-15
	# (saudi.sales: workspace visible but body blank). Only Guest is skipped.
	admin_was_blocked = "Administrator" in users
	for u in users:
		if u == "Guest":
			continue
		try:
			frappe.clear_cache(user=u)
		except Exception:
			pass
	try:
		frappe.cache.delete_value("workspace_sidebar_items")
	except Exception:
		pass

	print(
		f"[after_migrate] Unblocked Avientek module: cleared block rows on "
		f"{len(profiles)} profile(s) + synced {len(users)} user(s)"
		f"{' [Administrator was blocked — cleared its cache]' if admin_was_blocked else ''}"
	)


def _purge_custom_quote_project_field():
	"""Sridhar 2026-05-27: Custom Field Quotation-custom_quote_project keeps
	reappearing after live updates (module=None, not from our app's code or
	fixtures — likely re-added via Customize Form UI by someone). Deleted once
	via patch; this after_migrate hook ensures it stays gone on every bench
	migrate regardless of what re-creates it.
	"""
	field = "Quotation-custom_quote_project"
	if frappe.db.exists("Custom Field", field):
		frappe.delete_doc("Custom Field", field, ignore_permissions=True, force=True)
		frappe.db.commit()
		frappe.clear_cache(doctype="Quotation")
		print(f"[after_migrate] Purged stale Custom Field {field}")


def _sync_payment_voucher_formats():
	"""Push the on-disk Payment Voucher Professional + Fast print
	format JSON sources into their DB rows. Frappe's standard
	import path skips updating Print Format rows whose existing row
	has custom_format=1, so manual edits to the source JSON would
	otherwise never reach a running site. Calling the idempotent
	sync helper from after_migrate ensures every `bench migrate`
	re-syncs them — the helper is a no-op when DB already matches
	source, so it's safe to run on every migrate."""
	try:
		from avientek.patches.sync_payment_voucher_formats_v2026_04_27 import execute as _sync
		_sync()
	except Exception:
		frappe.log_error(
			title="after_migrate: PV format sync failed",
			message=frappe.get_traceback(),
		)


def _seed_quotation_approval_v3_workflow():
	"""Idempotent seed/refresh of the Quotation Approval Workflow Avientek (V3)
	on every migrate (Rahul/Sridhar 2026-05-08 — replaced the QAR 2-level
	flow with the SO-style Document Approval pattern). Source of truth lives
	in `avientek/patches/seed_quotation_approval_v3_workflow.py`."""
	try:
		from avientek.patches.seed_quotation_approval_v3_workflow import (
			seed,
		)
		seed()
	except Exception:
		frappe.log_error(
			title="after_migrate: Quotation V3 workflow seed failed",
			message=frappe.get_traceback(),
		)


def _block_prf_workflow_self_approval():
	"""Defensive re-assertion: set allow_self_approval=0 on every
	transition of every Payment Request Form workflow on every migrate.
	The patch in patches.txt does the one-shot retroactive fix; this
	helper guards against someone toggling it back to 1 in the UI
	(Sridhar 2026-05-06)."""
	try:
		from avientek.patches.block_prf_workflow_self_approval import (
			enforce_no_self_approval,
		)
		enforce_no_self_approval()
	except Exception:
		frappe.log_error(
			title="after_migrate: PRF self-approval block failed",
			message=frappe.get_traceback(),
		)


def _sync_sales_team_workspace():
	"""Push the Sales Team workspace's `number_cards` table + content
	from on-disk sales_team.json into the DB record. Frappe's reload-doc
	doesn't always propagate child-table changes for Workspace, so without
	this hook every migrate would leave the workspace stuck on whatever
	rows were originally inserted. Idempotent — overwrites with the
	on-disk state on every migrate. Sridhar 2026-05-06."""
	try:
		from avientek.scripts.sync_sales_team_workspace import run as _sync
		_sync()
	except Exception:
		frappe.log_error(
			title="after_migrate: Sales Team workspace sync failed",
			message=frappe.get_traceback(),
		)


def _create_asset_dam_fields():
	"""Add Demo Asset Management custom fields to the standard ERPNext Asset doctype."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	fields = [
		{
			"dt": "Asset",
			"fieldname": "custom_dam_section",
			"fieldtype": "Section Break",
			"label": "Demo Asset Management",
			"insert_after": "gross_purchase_amount",
			"collapsible": 1,
		},
		{
			"dt": "Asset",
			"fieldname": "custom_is_demo_asset",
			"fieldtype": "Check",
			"label": "Is Demo Asset",
			"description": "Mark if this asset is designated for demo purposes",
			"insert_after": "custom_dam_section",
			"in_standard_filter": 1,
			"allow_on_submit": 1,
		},
		{
			"dt": "Asset",
			"fieldname": "custom_dam_status",
			"fieldtype": "Select",
			"label": "Demo Status",
			"options": "\nFree\nOn Demo\nIssued as Standby",
			"default": "Free",
			"read_only": 1,
			"insert_after": "custom_is_demo_asset",
			"in_standard_filter": 1,
			"depends_on": "eval:doc.custom_is_demo_asset",
		},
		{
			"dt": "Asset",
			"fieldname": "custom_dam_customer",
			"fieldtype": "Link",
			"label": "Current Demo Customer",
			"options": "Customer",
			"read_only": 1,
			"insert_after": "custom_dam_status",
			"depends_on": "eval:doc.custom_is_demo_asset",
		},
		{
			"dt": "Asset",
			"fieldname": "custom_serial_no",
			"fieldtype": "Data",
			"label": "Serial No",
			"insert_after": "custom_dam_customer",
		},
		{
			"dt": "Asset",
			"fieldname": "custom_part_no",
			"fieldtype": "Data",
			"label": "Part No",
			"insert_after": "custom_serial_no",
		},
		{
			"dt": "Asset",
			"fieldname": "custom_dam_country",
			"fieldtype": "Link",
			"label": "Country",
			"options": "Country",
			"insert_after": "custom_owned_by",
		},
		{
			"dt": "Asset",
			"fieldname": "custom_dam_notes",
			"fieldtype": "Small Text",
			"label": "Notes",
			"insert_after": "custom_dam_country",
		},
	]

	for f in fields:
		fieldname = f["fieldname"]
		dt = f["dt"]
		cf_name = f"{dt}-{fieldname}"
		if not frappe.db.exists("Custom Field", cf_name):
			create_custom_field(dt, f)
		else:
			# Patch properties that may have changed after initial creation
			update_vals = {}
			if f.get("allow_on_submit"):
				update_vals["allow_on_submit"] = f["allow_on_submit"]
			# Ensure fieldtype and options stay in sync (e.g. Select → Link)
			if f.get("fieldtype"):
				update_vals["fieldtype"] = f["fieldtype"]
			if "options" in f:
				update_vals["options"] = f["options"]
			if update_vals:
				frappe.db.set_value("Custom Field", cf_name, update_vals)


def _fix_quotation_item_calc_layout():
	"""Ensure correct field ordering for Quotation Item expanded form.

	Runs after fixture sync so idx values aren't overwritten.
	Fixes:
	  - Pre-calc section (Standard Price, Special Price, Shipping Mode)
	  - 4-column calculation section with correct idx ordering
	  - Hides legacy fields and stale column breaks
	"""
	dt = "Quotation Item"

	# ── Create missing column breaks if needed ──
	for cb in [
		{"fieldname": "custom_column_break_calc_3", "insert_after": "custom_transport_value"},
	]:
		if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": cb["fieldname"]}):
			doc = frappe.new_doc("Custom Field")
			doc.dt = dt
			doc.fieldname = cb["fieldname"]
			doc.fieldtype = "Column Break"
			doc.insert_after = cb["insert_after"]
			doc.hidden = 0
			doc.insert()

	# ── Hide legacy fields and stale column breaks ──
	legacy = [
		"levee_per", "levee", "total_levee", "base_levee",
		"processing_charges_per", "processing_charges",
		"total_processing_charges", "base_processing_charges",
		"std_margin_per", "std_margin", "total_std_margin", "base_std_margin",
		"total_shipping", "total_reward", "base_shipping", "base_reward",
		"column_break_37", "column_break_38", "column_break_44",
	]
	for fn in legacy:
		cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fn}, "name")
		if cf:
			frappe.db.set_value("Custom Field", cf, "hidden", 1)

	# ── Full field chain: pre-calc section + 4-column calc section ──
	#
	# IMPORTANT: Standard Quotation Item fields have section/column breaks
	# at idx 35, 41, 51, 53, 55, 58, 60, 65, 68, 70, 73, 75.
	# If our custom fields use idx values in that range, standard breaks
	# interleave and create extra columns/sections in the layout.
	# Solution: start ALL custom fields at idx 100+, safely after all
	# standard fields (which end at idx ~75).
	#
	chain = [
		# Pre-calc section (Standard Price, Special Price, etc.)
		("custom_section_break_dkbzh", "usd_price_list_rate_with_margin"),
		("custom_standard_price_", "custom_section_break_dkbzh"),
		("custom_special_price", "custom_standard_price_"),
		("custom_special_price_note", "custom_special_price"),
		("custom_shipping_mode", "custom_special_price_note"),
		# Calc section: Col 1 — percentages
		("section_break_26", "custom_shipping_mode"),
		("shipping_per", "section_break_26"),
		("reward_per", "shipping_per"),
		("custom_finance_", "reward_per"),
		("custom_transport_", "custom_finance_"),
		# Calc section: Col 2 — values
		("shipping", "custom_transport_"),
		("reward", "shipping"),
		("custom_finance_value", "reward"),
		("custom_transport_value", "custom_finance_value"),
		# Calc section: Col 3 — calculation percentages
		("custom_column_break_calc_3", "custom_transport_value"),
		("custom_incentive_", "custom_column_break_calc_3"),
		("custom_customs_", "custom_incentive_"),
		("custom_markup_", "custom_customs_"),
		("custom_margin_", "custom_markup_"),
		("custom_special_rate", "custom_margin_"),
		("custom_discount_amount_value", "custom_special_rate"),
		("custom_discount_amount_qty", "custom_discount_amount_value"),
		# Calc section: Col 4 — calculation values
		("custom_incentive_value", "custom_discount_amount_qty"),
		("custom_customs_value", "custom_incentive_value"),
		("custom_markup_value", "custom_customs_value"),
		("custom_margin_value", "custom_markup_value"),
		("custom_selling_price", "custom_margin_value"),
		("custom_total_", "custom_selling_price"),
		("custom_cogs", "custom_total_"),
		("custom_addl_discount_amount", "custom_cogs"),
	]

	# Start at idx 100 — safely after ALL standard Quotation Item fields
	# (standard fields end at idx ~75)
	start_idx = 100

	for i, (fieldname, after) in enumerate(chain):
		cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "name")
		if cf:
			frappe.db.set_value("Custom Field", cf, {"idx": start_idx + i, "insert_after": after})

	# Also move hidden legacy fields to idx 200+ so they don't interfere
	legacy_start = 200
	legacy_fields = frappe.db.get_all(
		"Custom Field",
		filters={"dt": dt, "hidden": 1, "fieldname": ["not in", [
			"usd_price_list_rate_with_margin", "tax_rate", "tax_amount", "total_amount",
		]]},
		fields=["name", "fieldname"],
		order_by="idx",
	)
	for j, lf in enumerate(legacy_fields):
		frappe.db.set_value("Custom Field", lf["name"], "idx", legacy_start + j)

	frappe.db.commit()


def _fix_global_field_settings():
	"""Fix field settings that must persist across all servers.

	Runs on every migrate to ensure these settings are always correct,
	regardless of DB state or which server is being migrated.
	"""
	# 1. Hide fields on Quotation / Quotation Item
	hide_fields = [
		("Quotation", "is_reverse_charge"),
		("Quotation Item", "discount_and_margin"),
	]
	for dt, fn in hide_fields:
		has_field = (
			frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fn})
			or frappe.get_meta(dt).has_field(fn)
		)
		if has_field and not frappe.db.exists("Property Setter", {
			"doc_type": dt, "field_name": fn, "property": "hidden"
		}):
			make_property_setter(dt, fn, "hidden", "1", "Check")

	# 2. Make custom_quote_type optional on Sales Invoice and Sales Order
	for dt in ["Sales Invoice", "Sales Order"]:
		cf = frappe.db.exists("Custom Field", f"{dt}-custom_quote_type")
		if cf:
			frappe.db.set_value("Custom Field", cf, "reqd", 0)

	# 3. Set ignore_user_permissions on ALL Quotation custom child tables
	# Prevents "Not permitted" errors for users with Company restrictions
	for fn in ["custom_stock", "custom_brand_summary", "custom_history",
			   "custom_quotation_brand_summary", "custom_service_items",
			   "custom_shipment_and_margin", "optional_items"]:
		cf = frappe.db.exists("Custom Field", f"Quotation-{fn}")
		if cf:
			frappe.db.set_value("Custom Field", cf, "ignore_user_permissions", 1)

	# 3b. Also set ignore_user_permissions on Company Link field INSIDE child DocTypes
	# The parent table field's ignore_user_permissions alone is not enough —
	# Frappe also checks the Link field inside the child table row
	frappe.db.sql("""
		UPDATE tabDocField SET ignore_user_permissions=1
		WHERE parent='Quotation Stock' AND fieldname='company' AND options='Company'
	""")

	# 4. Delete stale column breaks from Quotation Item (permanent cleanup)
	for fn in ["column_break_32", "column_break_38", "custom_column_break_calc_4", "custom_column_break_9d6lj"]:
		cf_name = f"Quotation Item-{fn}"
		if frappe.db.exists("Custom Field", cf_name):
			frappe.delete_doc("Custom Field", cf_name, force=True)

	frappe.db.commit()


def _enforce_custom_role_permissions():
	"""Ensure custom role permissions stay as intended after every migrate.

	Reads the baseline from `avientek/data/role_perm_baseline.json` instead
	of using a hardcoded dict, so client-edited values that need to be
	preserved can flow into the repo via `tools/sync_fixtures.py` and
	become the new baseline on the next deploy. Avoids the trap where
	migrate silently reverts client UI changes (Sridhar 2026-05-04).

	For each row in the baseline:
	  - cleans up duplicate Custom DocPerm rows (legacy bug, keep oldest)
	  - sets every perm flag listed under `perms` on the kept row
	  - if no row exists and `create_if_missing` is true, inserts one
	  - if no row exists and `create_if_missing` is false, skips silently
	    (used for built-in roles whose row only exists on production)
	"""
	baseline = _load_role_perm_baseline()
	if not baseline:
		return
	for row in baseline.get("rows", []):
		dt = row.get("parent")
		role = row.get("role")
		permlevel = row.get("permlevel", 0)
		perms = row.get("perms") or {}
		create_if_missing = bool(row.get("create_if_missing"))
		if not (dt and role and perms):
			continue
		all_rows = frappe.db.get_all(
			"Custom DocPerm",
			filters={"parent": dt, "role": role, "permlevel": permlevel},
			pluck="name",
			order_by="creation",
		)
		if all_rows:
			keep = all_rows[0]
			for dup in all_rows[1:]:
				frappe.db.sql("DELETE FROM `tabCustom DocPerm` WHERE name=%s", dup)
			frappe.db.set_value("Custom DocPerm", keep, perms)
		elif create_if_missing:
			doc = frappe.new_doc("Custom DocPerm")
			doc.parent = dt
			doc.role = role
			doc.permlevel = permlevel
			doc.update(perms)
			doc.insert(ignore_permissions=True)
	frappe.db.commit()


def _enforce_export_permissions():
	"""Deprecated — kept as a stub so any external caller doesn't break.
	Logic merged into `_enforce_custom_role_permissions` which now reads
	all role baselines from `data/role_perm_baseline.json`."""
	return


def _load_role_perm_baseline():
	"""Load `avientek/data/role_perm_baseline.json`. Returns dict or None
	if the file is missing/unreadable — in which case migrate skips role
	enforcement rather than failing (intentional: lets us land the JSON
	migration in a safe order)."""
	import json as _json
	import os as _os
	try:
		path = _os.path.join(
			frappe.get_app_path("avientek"), "data", "role_perm_baseline.json"
		)
		if not _os.path.isfile(path):
			return None
		with open(path) as fh:
			return _json.load(fh)
	except Exception:
		frappe.log_error(
			title="role_perm_baseline.json load failed",
			message=frappe.get_traceback(),
		)
		return None


def _deactivate_old_quotation_workflows():
	"""Deactivate old Quotation workflows when Quotation Final exists."""
	if not frappe.db.exists("Workflow", "Quotation Final"):
		return
	old_workflows = ["Quotation Margin Approval", "Quotation DocFlow", "Quotation"]
	for wf_name in old_workflows:
		if frappe.db.exists("Workflow", wf_name):
			wf = frappe.get_doc("Workflow", wf_name)
			if wf.is_active:
				wf.is_active = 0
				wf.save(ignore_permissions=True)
				frappe.logger().info(f"Deactivated old workflow: {wf_name}")


@frappe.whitelist()
def retry_failed_repost_item_valuation(company=None):
	"""Retry all failed Repost Item Valuation entries for a company.
	Sets status back to Queued so the scheduler picks them up."""
	if frappe.session.user != "Administrator":
		frappe.throw(_("Only Administrator can retry repost entries."))

	filters = {"status": "Failed", "docstatus": 1}
	if company:
		filters["company"] = company

	failed = frappe.get_all(
		"Repost Item Valuation",
		filters=filters,
		fields=["name"],
		pluck="name",
	)

	if not failed:
		return {"message": "No failed entries found", "count": 0}

	for name in failed:
		frappe.db.set_value(
			"Repost Item Valuation", name, "status", "Queued",
			update_modified=False,
		)

	frappe.db.commit()
	return {"message": f"Queued {len(failed)} entries for retry", "count": len(failed)}
