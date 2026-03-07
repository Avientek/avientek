import frappe
from frappe import _
from frappe.utils import flt, cint


def before_submit(doc, method=None):
	"""Validate that batch-tracked stock items have a batch selected."""
	for row in doc.stock_items:
		if not row.item_code:
			continue
		has_batch = frappe.get_cached_value("Item", row.item_code, "has_batch_no")
		if has_batch and not row.batch_no and not row.get("serial_and_batch_bundle"):
			frappe.throw(
				_("Row #{0}: Item {1} requires a Batch No. Please select a batch before submitting.").format(
					row.idx, row.item_code
				)
			)


def on_submit(doc, method=None):
	"""After ERPNext creates the composite asset and handles GL/SLE,
	create individual Asset records — one per unit per stock item line.

	The composite asset (created by ERPNext) handles the capitalization
	GL entries.  The individual assets are for physical tracking and
	depreciation scheduling.
	"""
	if not doc.stock_items:
		return

	# Delete the composite asset created by ERPNext's create_target_asset().
	# It's only a draft placeholder — GL/SLE entries reference the
	# Asset Capitalization voucher, not the composite asset.
	# We replace it with individual assets below.
	composite_asset = doc.target_asset
	if composite_asset and frappe.db.exists("Asset", composite_asset):
		composite = frappe.get_doc("Asset", composite_asset)
		if composite.docstatus == 0:
			# Clear the link on the capitalization so delete doesn't fail
			doc.db_set("target_asset", "")
			# Also clear any Asset Movement records that reference it
			frappe.db.delete("Asset Movement Item", {"asset": composite_asset})
			frappe.db.delete("Asset Activity", {"asset": composite_asset})
			frappe.delete_doc(
				"Asset", composite_asset,
				force=True, ignore_permissions=True, delete_permanently=True
			)

	target_item = frappe.get_cached_doc("Item", doc.target_item_code)
	asset_category = target_item.asset_category

	created_assets = []

	for item in doc.stock_items:
		stock_item = frappe.get_cached_doc("Item", item.item_code)
		qty = cint(item.stock_qty) or 1
		per_unit_value = flt(item.amount / qty, 2) if qty else flt(item.amount, 2)

		for i in range(qty):
			asset = frappe.new_doc("Asset")
			asset.company = doc.company
			asset.item_code = doc.target_item_code
			asset.asset_name = stock_item.item_name
			asset.asset_category = asset_category
			asset.location = doc.target_asset_location
			asset.purchase_date = doc.posting_date
			asset.available_for_use_date = doc.posting_date
			asset.gross_purchase_amount = per_unit_value
			asset.purchase_amount = per_unit_value
			asset.asset_owner = "Company"
			asset.asset_owner_company = doc.company
			asset.custom_is_demo_asset = 1
			asset.custom_asset_capitalization = doc.name
			asset.calculate_depreciation = 1

			# Part number from the stock item
			if stock_item.get("part_number"):
				asset.custom_part_no = stock_item.part_number

			# Pre-populate finance_books from Asset Category before insert,
			# because validate_asset_values() checks for finance_books
			# before set_missing_values() populates them.
			asset.set_missing_values()
			asset.flags.asset_created_via_asset_capitalization = True
			asset.insert()

			# Submit the asset
			asset.submit()

			created_assets.append(asset.name)

	if created_assets:
		# Store individual asset names on the capitalization for cancel tracking,
		# and set target_asset to the first one so the sidebar connection works.
		doc.db_set({
			"custom_individual_assets": ",".join(created_assets),
			"target_asset": created_assets[0],
		})

		frappe.msgprint(
			_("{0} individual asset(s) created and submitted: {1}").format(
				len(created_assets),
				", ".join(
					f'<a href="/app/asset/{a}">{a}</a>' for a in created_assets
				),
			),
			title=_("Assets Created"),
			indicator="green",
		)


def on_cancel(doc, method=None):
	"""Cancel individual assets that were created on submit."""
	individual_assets = (doc.get("custom_individual_assets") or "").strip()
	if not individual_assets:
		return

	asset_names = [a.strip() for a in individual_assets.split(",") if a.strip()]

	for asset_name in asset_names:
		if not frappe.db.exists("Asset", asset_name):
			continue

		asset = frappe.get_doc("Asset", asset_name)
		if asset.docstatus == 1:
			asset.flags.ignore_validate = True
			asset.cancel()

	doc.db_set("custom_individual_assets", "")


@frappe.whitelist()
def recreate_cancelled_assets(docname):
	"""Recreate individual assets that were cancelled.

	Looks at custom_individual_assets, finds cancelled ones,
	creates new assets to replace them, and updates the list.
	"""
	doc = frappe.get_doc("Asset Capitalization", docname)
	if doc.docstatus != 1:
		frappe.throw(_("Asset Capitalization must be submitted"))

	individual_assets = (doc.get("custom_individual_assets") or "").strip()
	if not individual_assets:
		frappe.throw(_("No individual assets found on this capitalization"))

	asset_names = [a.strip() for a in individual_assets.split(",") if a.strip()]

	target_item = frappe.get_cached_doc("Item", doc.target_item_code)
	asset_category = target_item.asset_category

	# Build a map of stock item → per_unit_value for recreating
	stock_item_map = {}
	for item in doc.stock_items:
		qty = cint(item.stock_qty) or 1
		per_unit_value = flt(item.amount / qty, 2) if qty else flt(item.amount, 2)
		stock_item = frappe.get_cached_doc("Item", item.item_code)
		stock_item_map[item.item_code] = {
			"per_unit_value": per_unit_value,
			"stock_item": stock_item,
		}

	new_assets = []
	kept_assets = []

	for asset_name in asset_names:
		if not frappe.db.exists("Asset", asset_name):
			continue

		asset_doc = frappe.get_doc("Asset", asset_name)
		if asset_doc.docstatus == 2:
			# Cancelled — recreate it
			# Find the matching stock item by asset_name
			stock_info = None
			for item_code, info in stock_item_map.items():
				if info["stock_item"].item_name == asset_doc.asset_name:
					stock_info = info
					break

			if not stock_info:
				# Fallback: use first stock item
				stock_info = next(iter(stock_item_map.values()))

			new_asset = frappe.new_doc("Asset")
			new_asset.company = doc.company
			new_asset.item_code = doc.target_item_code
			new_asset.asset_name = asset_doc.asset_name
			new_asset.asset_category = asset_category
			new_asset.location = doc.target_asset_location
			new_asset.purchase_date = doc.posting_date
			new_asset.available_for_use_date = doc.posting_date
			new_asset.gross_purchase_amount = stock_info["per_unit_value"]
			new_asset.purchase_amount = stock_info["per_unit_value"]
			new_asset.asset_owner = "Company"
			new_asset.asset_owner_company = doc.company
			new_asset.custom_is_demo_asset = 1
			new_asset.custom_asset_capitalization = doc.name
			new_asset.calculate_depreciation = 1

			if stock_info["stock_item"].get("part_number"):
				new_asset.custom_part_no = stock_info["stock_item"].part_number

			new_asset.set_missing_values()
			new_asset.flags.asset_created_via_asset_capitalization = True
			new_asset.insert()
			new_asset.submit()

			new_assets.append(new_asset.name)
		else:
			kept_assets.append(asset_name)

	if not new_assets:
		frappe.msgprint(_("No cancelled assets to recreate"), indicator="orange")
		return

	# Update the individual assets list
	all_assets = kept_assets + new_assets
	doc.db_set("custom_individual_assets", ",".join(all_assets))

	frappe.msgprint(
		_("{0} asset(s) recreated: {1}").format(
			len(new_assets),
			", ".join(
				f'<a href="/app/asset/{a}">{a}</a>' for a in new_assets
			),
		),
		title=_("Assets Recreated"),
		indicator="green",
	)


@frappe.whitelist()
def get_decapitalization_defaults(asset_name):
	"""Return stock item details from the Asset Capitalization that created this asset.

	Used to pre-fill Asset Decapitalization form fields (target_item_code,
	target_warehouse, batch_no).
	"""
	cap_name = frappe.db.get_value("Asset", asset_name, "custom_asset_capitalization")
	if not cap_name:
		return {}

	doc = frappe.get_doc("Asset Capitalization", cap_name)
	asset_doc = frappe.get_doc("Asset", asset_name)

	# Find the matching stock item row by comparing asset_name with item_name
	matched_row = None
	for row in doc.stock_items:
		stock_item_name = frappe.get_cached_value("Item", row.item_code, "item_name")
		if stock_item_name == asset_doc.asset_name:
			matched_row = row
			break

	# Fallback to first stock item if no match
	if not matched_row and doc.stock_items:
		matched_row = doc.stock_items[0]

	if not matched_row:
		return {}

	return {
		"target_item_code": matched_row.item_code,
		"target_warehouse": matched_row.warehouse,
		"batch_no": matched_row.batch_no or "",
	}


@frappe.whitelist()
def get_depreciation_expense_account(asset_category, company):
	"""Return the depreciation expense account from Asset Category for the given company."""
	if not asset_category or not company:
		return ""

	account = frappe.db.get_value(
		"Asset Category Account",
		{"parent": asset_category, "company_name": company},
		"depreciation_expense_account",
	)
	return account or ""
