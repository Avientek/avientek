import frappe
from frappe import _
from frappe.utils import flt


# ── Mapping: parent doctype → child item doctype ──
BRAND_DOCTYPES = {
	"Quotation": "Quotation Item",
	"Sales Order": "Sales Order Item",
	"Sales Invoice": "Sales Invoice Item",
	"Delivery Note": "Delivery Note Item",
	"POS Invoice": "POS Invoice Item",
	"Purchase Order": "Purchase Order Item",
	"Purchase Receipt": "Purchase Receipt Item",
	"Purchase Invoice": "Purchase Invoice Item",
	"Material Request": "Material Request Item",
	"Supplier Quotation": "Supplier Quotation Item",
	"Request for Quotation": "Request for Quotation Item",
	"Opportunity": "Opportunity Item",
	"Avientek Proforma Invoice": "Proforma Invoice Item",
	"Existing Quotation": "Existing Quotation Item",
}

# Parent-level doctypes where brand is directly on the parent
BRAND_PARENT_DOCTYPES = ["Item", "Serial No", "Item Price", "Demo Unit Request"]

# Doctypes with item_group on CHILD item table (same set as brand)
ITEM_GROUP_DOCTYPES = {
	"Quotation": "Quotation Item",
	"Sales Order": "Sales Order Item",
	"Sales Invoice": "Sales Invoice Item",
	"Delivery Note": "Delivery Note Item",
	"POS Invoice": "POS Invoice Item",
	"Purchase Order": "Purchase Order Item",
	"Purchase Receipt": "Purchase Receipt Item",
	"Purchase Invoice": "Purchase Invoice Item",
	"Material Request": "Material Request Item",
	"Supplier Quotation": "Supplier Quotation Item",
	"Request for Quotation": "Request for Quotation Item",
	"Opportunity": "Opportunity Item",
	"Avientek Proforma Invoice": "Proforma Invoice Item",
	"Existing Quotation": "Existing Quotation Item",
}

# Parent-level doctypes where item_group is directly on the parent
ITEM_GROUP_PARENT_DOCTYPES = ["Item"]


def _get_user_brands(user=None):
	"""Get list of permitted brands for a user. Returns empty list if no restriction."""
	user = user or frappe.session.user
	if user == "Administrator":
		return []
	return frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Brand"},
		pluck="for_value",
	)


def _get_user_item_groups(user=None):
	"""Get list of permitted item groups for a user. Returns empty list if no restriction."""
	user = user or frappe.session.user
	if user == "Administrator":
		return []
	return frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Item Group"},
		pluck="for_value",
	)


@frappe.whitelist()
def check_user_has_item_group_restriction():
	"""Quick check: does the current user have any Item Group User Permissions?"""
	user = frappe.session.user
	if user == "Administrator":
		return False
	return bool(frappe.db.exists("User Permission", {"user": user, "allow": "Item Group"}))


@frappe.whitelist()
def check_user_has_brand_restriction():
	"""Quick check: does the current user have any Brand User Permissions?"""
	user = frappe.session.user
	if user == "Administrator":
		return False
	return bool(frappe.db.exists("User Permission", {"user": user, "allow": "Brand"}))


@frappe.whitelist()
def get_permitted_doc_preview(doctype, docname):
	"""Return document data filtered to only items the current user has Brand/Item Group permission for.

	Works for any doctype that has a child item table with brand or item_group fields.
	"""
	user = frappe.session.user
	if user == "Administrator":
		return {"full_access": True}

	brand_perms = _get_user_brands(user)
	item_group_perms = _get_user_item_groups(user)

	# No restrictions at all
	if not brand_perms and not item_group_perms:
		return {"full_access": True}

	# Validate doctype is one we support
	child_dt = BRAND_DOCTYPES.get(doctype) or ITEM_GROUP_DOCTYPES.get(doctype)
	is_parent_brand = doctype in BRAND_PARENT_DOCTYPES
	is_parent_item_group = doctype in ITEM_GROUP_PARENT_DOCTYPES

	if not child_dt and not is_parent_brand and not is_parent_item_group:
		return {"full_access": True}

	# Handle parent-level doctypes (Item, Serial No, Item Price)
	if is_parent_brand or is_parent_item_group:
		doc = frappe.get_doc(doctype, docname)
		blocked = []
		if brand_perms and is_parent_brand:
			doc_brand = doc.get("brand") or ""
			if doc_brand and doc_brand not in brand_perms:
				blocked.append(_("Brand '{0}'").format(doc_brand))
		if item_group_perms and is_parent_item_group:
			doc_ig = doc.get("item_group") or ""
			if doc_ig and doc_ig not in item_group_perms:
				blocked.append(_("Item Group '{0}'").format(doc_ig))
		if not blocked:
			return {"full_access": True}
		return {
			"full_access": False,
			"doc_name": doc.name,
			"doctype": doctype,
			"restricted": True,
			"message": _("You do not have permission to access {0}").format(", ".join(blocked)),
		}

	# Handle child-item doctypes
	doc = frappe.get_doc(doctype, docname)

	# Find child table fieldname
	items_field = "items"
	for df in doc.meta.get_table_fields():
		if df.options == child_dt:
			items_field = df.fieldname
			break

	child_items = doc.get(items_field) or []

	permitted_items = []
	restricted_count = 0
	for item in child_items:
		item_brand = item.get("brand") or ""
		item_ig = item.get("item_group") or ""

		# Check brand restriction
		brand_ok = not brand_perms or not item_brand or item_brand in brand_perms
		# Check item group restriction
		ig_ok = not item_group_perms or not item_ig or item_ig in item_group_perms

		if brand_ok and ig_ok:
			permitted_items.append({
				"idx": item.idx,
				"item_code": item.get("item_code") or "",
				"item_name": item.get("item_name") or "",
				"brand": item_brand,
				"item_group": item_ig,
				"qty": flt(item.get("qty"), 2),
				"rate": flt(item.get("rate"), 2),
				"amount": flt(item.get("amount"), 2),
				"uom": item.get("uom") or "",
			})
		else:
			restricted_count += 1

	# If ALL items pass both brand and item group checks, allow full document access
	if restricted_count == 0:
		return {"full_access": True}

	permitted_amount = sum(flt(i["amount"]) for i in permitted_items)

	# Get customer/supplier/party name
	party = (
		doc.get("party_name")
		or doc.get("customer_name")
		or doc.get("customer")
		or doc.get("supplier_name")
		or doc.get("supplier")
		or ""
	)

	currency = doc.get("currency") or "USD"

	return {
		"full_access": False,
		"doc_name": doc.name,
		"doctype": doctype,
		"party": party,
		"transaction_date": str(doc.get("transaction_date") or doc.get("posting_date") or ""),
		"status": doc.get("status") or "",
		"currency": currency,
		"total_items": len(child_items),
		"permitted_items": permitted_items,
		"permitted_count": len(permitted_items),
		"restricted_count": restricted_count,
		"permitted_amount": flt(permitted_amount, 2),
		"grand_total": flt(doc.get("grand_total") or doc.get("total"), 2),
	}


# ── permission_query_conditions generators ──

def _brand_permission_query(user, parent_dt, child_dt):
	"""Generic permission query for any parent doctype with brand items."""
	if user == "Administrator":
		return ""

	brand_perms = _get_user_brands(user)
	if not brand_perms:
		return ""

	brands_sql = ", ".join(frappe.db.escape(b) for b in brand_perms)
	parent_table = "`tab{}`".format(parent_dt)
	child_table = "`tab{}`".format(child_dt)

	exists_cond = (
		"EXISTS ("
		"SELECT 1 FROM {child} qi "
		"WHERE qi.parent = {parent}.name "
		"AND (qi.brand IN ({brands}) OR IFNULL(qi.brand, '') = '')"
		")"
	).format(child=child_table, parent=parent_table, brands=brands_sql)

	# Check if report view (child table is joined in query)
	import json
	fields = frappe.local.form_dict.get("fields") or []
	if isinstance(fields, str):
		try:
			fields = json.loads(fields)
		except Exception:
			fields = []

	fields_str = str(fields)
	conditions = [exists_cond]

	# Filter item child table rows in report view
	if any(child_table in str(f) for f in fields):
		conditions.append(
			"({child}.`brand` IN ({brands}) OR IFNULL({child}.`brand`, '') = '')".format(
				child=child_table, brands=brands_sql
			)
		)

	# Filter Brand Summary child table rows in report view (Quotation only)
	brand_summary_table = "`tabQuotation Brand Summary`"
	if parent_dt == "Quotation" and brand_summary_table in fields_str:
		conditions.append(
			"({bs}.`brand` IN ({brands}) OR IFNULL({bs}.`brand`, '') = '')".format(
				bs=brand_summary_table, brands=brands_sql
			)
		)

	return " AND ".join(conditions)


def _brand_parent_permission_query(user, parent_dt):
	"""Permission query for doctypes where brand is on the parent (Item, Serial No, etc.)."""
	if user == "Administrator":
		return ""

	brand_perms = _get_user_brands(user)
	if not brand_perms:
		return ""

	brands_sql = ", ".join(frappe.db.escape(b) for b in brand_perms)
	parent_table = "`tab{}`".format(parent_dt)

	# Also show items with no brand set (empty/null)
	return "({parent}.`brand` IN ({brands}) OR IFNULL({parent}.`brand`, '') = '')".format(
		parent=parent_table, brands=brands_sql
	)



# ── Item Group permission query generators ──

def _item_group_permission_query(user, parent_dt, child_dt):
	"""Generic permission query for any parent doctype with item_group on child items."""
	if user == "Administrator":
		return ""

	ig_perms = _get_user_item_groups(user)
	if not ig_perms:
		return ""

	igs_sql = ", ".join(frappe.db.escape(ig) for ig in ig_perms)
	parent_table = "`tab{}`".format(parent_dt)
	child_table = "`tab{}`".format(child_dt)

	exists_cond = (
		"EXISTS ("
		"SELECT 1 FROM {child} qi "
		"WHERE qi.parent = {parent}.name "
		"AND (qi.item_group IN ({igs}) OR IFNULL(qi.item_group, '') = '')"
		")"
	).format(child=child_table, parent=parent_table, igs=igs_sql)

	import json
	fields = frappe.local.form_dict.get("fields") or []
	if isinstance(fields, str):
		try:
			fields = json.loads(fields)
		except Exception:
			fields = []

	is_report_view = any(child_table in str(f) for f in fields)

	if is_report_view:
		return "{exists} AND ({child}.`item_group` IN ({igs}) OR IFNULL({child}.`item_group`, '') = '')".format(
			exists=exists_cond, child=child_table, igs=igs_sql
		)

	return exists_cond


def _item_group_parent_permission_query(user, parent_dt):
	"""Permission query for doctypes where item_group is on the parent (Item)."""
	if user == "Administrator":
		return ""

	ig_perms = _get_user_item_groups(user)
	if not ig_perms:
		return ""

	igs_sql = ", ".join(frappe.db.escape(ig) for ig in ig_perms)
	parent_table = "`tab{}`".format(parent_dt)

	return "({parent}.`item_group` IN ({igs}) OR IFNULL({parent}.`item_group`, '') = '')".format(
		parent=parent_table, igs=igs_sql
	)


# ── Combined permission query (brand + item group) for each doctype ──

def _combined_permission_query(user, parent_dt, child_dt):
	"""Combine brand and item group permission queries for a child-item doctype."""
	parts = []
	brand_cond = _brand_permission_query(user, parent_dt, child_dt)
	if brand_cond:
		parts.append(brand_cond)
	ig_cond = _item_group_permission_query(user, parent_dt, child_dt)
	if ig_cond:
		parts.append(ig_cond)
	return " AND ".join(parts)


def _combined_parent_permission_query(user, parent_dt):
	"""Combine brand and item group permission queries for a parent-level doctype."""
	parts = []
	if parent_dt in BRAND_PARENT_DOCTYPES:
		brand_cond = _brand_parent_permission_query(user, parent_dt)
		if brand_cond:
			parts.append(brand_cond)
	if parent_dt in ITEM_GROUP_PARENT_DOCTYPES:
		ig_cond = _item_group_parent_permission_query(user, parent_dt)
		if ig_cond:
			parts.append(ig_cond)
	return " AND ".join(parts)


# ── Individual permission query functions (referenced from hooks.py) ──

def quotation_permission_query(user):
	return _combined_permission_query(user, "Quotation", "Quotation Item")

def sales_order_permission_query(user):
	return _combined_permission_query(user, "Sales Order", "Sales Order Item")

def sales_invoice_permission_query(user):
	return _combined_permission_query(user, "Sales Invoice", "Sales Invoice Item")

def delivery_note_permission_query(user):
	return _combined_permission_query(user, "Delivery Note", "Delivery Note Item")

def pos_invoice_permission_query(user):
	return _combined_permission_query(user, "POS Invoice", "POS Invoice Item")

def purchase_order_permission_query(user):
	return _combined_permission_query(user, "Purchase Order", "Purchase Order Item")

def purchase_receipt_permission_query(user):
	return _combined_permission_query(user, "Purchase Receipt", "Purchase Receipt Item")

def purchase_invoice_permission_query(user):
	return _combined_permission_query(user, "Purchase Invoice", "Purchase Invoice Item")

def material_request_permission_query(user):
	return _combined_permission_query(user, "Material Request", "Material Request Item")

def supplier_quotation_permission_query(user):
	return _combined_permission_query(user, "Supplier Quotation", "Supplier Quotation Item")

def request_for_quotation_permission_query(user):
	return _combined_permission_query(user, "Request for Quotation", "Request for Quotation Item")

def opportunity_permission_query(user):
	return _combined_permission_query(user, "Opportunity", "Opportunity Item")

def item_permission_query(user):
	return _combined_parent_permission_query(user, "Item")

def serial_no_permission_query(user):
	return _combined_parent_permission_query(user, "Serial No")

def item_price_permission_query(user):
	return _combined_parent_permission_query(user, "Item Price")

# Avientek custom doctypes
def demo_unit_request_permission_query(user):
	return _combined_parent_permission_query(user, "Demo Unit Request")

def proforma_invoice_permission_query(user):
	return _combined_permission_query(user, "Avientek Proforma Invoice", "Proforma Invoice Item")

def existing_quotation_permission_query(user):
	return _combined_permission_query(user, "Existing Quotation", "Existing Quotation Item")


@frappe.whitelist()
def get_permitted_brands():
	"""Return the list of permitted brands for the current user."""
	user = frappe.session.user
	if user == "Administrator":
		return []
	return _get_user_brands(user)


@frappe.whitelist()
def get_permitted_item_groups():
	"""Return the list of permitted item groups for the current user."""
	user = frappe.session.user
	if user == "Administrator":
		return []
	return _get_user_item_groups(user)
