import frappe
from frappe import _
from frappe.utils import flt, fmt_money


@frappe.whitelist()
def get_permitted_quotation_preview(quotation_name):
	"""Return quotation data filtered to only items the current user has Brand permission for.

	Called when a restricted user clicks a Quotation they cannot fully access.
	Uses ignore_permissions to read the doc, then filters items by the user's
	Brand User Permissions.
	"""
	user = frappe.session.user
	if user == "Administrator":
		return {"full_access": True}

	# Get user's permitted brands
	brand_perms = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Brand"},
		pluck="for_value",
	)

	# If user has no Brand restrictions at all, they have full access
	if not brand_perms:
		return {"full_access": True}

	# Read quotation bypassing permissions
	doc = frappe.get_doc("Quotation", quotation_name)

	# Filter items to only permitted brands
	permitted_items = []
	restricted_count = 0
	for item in doc.items:
		item_brand = item.get("brand") or ""
		if item_brand in brand_perms:
			permitted_items.append({
				"idx": item.idx,
				"item_code": item.item_code,
				"item_name": item.item_name,
				"brand": item_brand,
				"qty": item.qty,
				"rate": flt(item.rate, 2),
				"amount": flt(item.amount, 2),
				"uom": item.uom or "",
				"custom_selling_price": flt(item.get("custom_selling_price"), 2),
				"custom_selling_amount": flt(item.get("custom_selling_amount") or item.amount, 2),
			})
		else:
			restricted_count += 1

	# Compute totals for permitted items only
	permitted_total = sum(flt(i["custom_selling_amount"]) for i in permitted_items)
	permitted_amount = sum(flt(i["amount"]) for i in permitted_items)

	currency = doc.currency or "USD"
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency") or "AED"

	return {
		"full_access": False,
		"quotation_name": doc.name,
		"customer": doc.party_name or doc.customer_name,
		"transaction_date": str(doc.transaction_date),
		"status": doc.status,
		"currency": currency,
		"company_currency": company_currency,
		"total_items": len(doc.items),
		"permitted_items": permitted_items,
		"permitted_count": len(permitted_items),
		"restricted_count": restricted_count,
		"permitted_total": flt(permitted_total, 2),
		"permitted_amount": flt(permitted_amount, 2),
		"grand_total": flt(doc.grand_total, 2),
		"permitted_brands": brand_perms,
	}


@frappe.whitelist()
def check_user_has_brand_restriction():
	"""Quick check: does the current user have any Brand User Permissions?"""
	user = frappe.session.user
	if user == "Administrator":
		return False
	return frappe.db.exists("User Permission", {"user": user, "allow": "Brand"})


def quotation_permission_query(user):
	"""permission_query_conditions hook for Quotation.

	For users with Brand User Permissions:
	- List View: only show Quotations that have at least one permitted-brand item
	- Report View: also filter individual item rows to permitted brands only
	"""
	if user == "Administrator":
		return ""

	brand_perms = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Brand"},
		pluck="for_value",
	)

	if not brand_perms:
		return ""  # no brand restriction

	brands_sql = ", ".join(frappe.db.escape(b) for b in brand_perms)

	# Base condition: EXISTS subquery (works in list view and report view)
	exists_cond = (
		"EXISTS ("
		"SELECT 1 FROM `tabQuotation Item` qi "
		"WHERE qi.parent = `tabQuotation`.name "
		"AND qi.brand IN ({brands})"
		")"
	).format(brands=brands_sql)

	# Check if this is a report view query (child table is joined)
	import json
	fields = frappe.local.form_dict.get("fields") or []
	if isinstance(fields, str):
		try:
			fields = json.loads(fields)
		except Exception:
			fields = []

	is_report_view = any("`tabQuotation Item`" in str(f) for f in fields)

	if is_report_view:
		# Report view: also filter child-table rows to permitted brands
		return (
			"{exists} AND `tabQuotation Item`.`brand` IN ({brands})"
		).format(exists=exists_cond, brands=brands_sql)

	return exists_cond
