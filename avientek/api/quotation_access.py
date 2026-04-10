import io

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

# Doctypes with customer_group on the parent document
CUSTOMER_GROUP_PARENT_DOCTYPES = [
	"Quotation", "Sales Order", "Sales Invoice", "Delivery Note",
	"POS Invoice", "Opportunity",
]

# Doctypes with supplier_group on the parent document
SUPPLIER_GROUP_PARENT_DOCTYPES = ["Purchase Invoice"]

# Doctypes with Sales Team child table (sales_person field)
SALES_PERSON_DOCTYPES = ["Sales Order", "Sales Invoice", "Delivery Note", "POS Invoice"]

# Doctypes with sales_person as a parent-level Link field (not Sales Team child table)
SALES_PERSON_PARENT_DOCTYPES = ["Quotation"]


def _get_user_perms(user, allow_type):
	"""Get permitted values for a user. Uses direct SQL to bypass permission checks
	on the User Permission doctype itself (restricted users can't always read their own perms)."""
	if not user or user == "Administrator":
		return []
	return frappe.db.sql(
		"SELECT for_value FROM `tabUser Permission` WHERE user=%s AND allow=%s",
		(user, allow_type),
		pluck="for_value",
	) or []


def _get_user_brands(user=None):
	return _get_user_perms(user or frappe.session.user, "Brand")


def _get_user_item_groups(user=None):
	return _get_user_perms(user or frappe.session.user, "Item Group")


def _get_user_customer_groups(user=None):
	return _get_user_perms(user or frappe.session.user, "Customer Group")


def _get_user_supplier_groups(user=None):
	return _get_user_perms(user or frappe.session.user, "Supplier Group")


def _get_user_sales_persons(user=None):
	return _get_user_perms(user or frappe.session.user, "Sales Person")


def _get_user_companies(user=None):
	return _get_user_perms(user or frappe.session.user, "Company")


def _has_user_perm(allow_type):
	"""Check if user has a User Permission of given type. Uses direct SQL."""
	user = frappe.session.user
	if user == "Administrator":
		return False
	return bool(frappe.db.sql(
		"SELECT 1 FROM `tabUser Permission` WHERE user=%s AND allow=%s LIMIT 1",
		(user, allow_type),
	))


@frappe.whitelist()
def check_user_has_item_group_restriction():
	return _has_user_perm("Item Group")


@frappe.whitelist()
def check_user_has_brand_restriction():
	return _has_user_perm("Brand")


@frappe.whitelist()
def check_user_has_customer_group_restriction():
	return _has_user_perm("Customer Group")


@frappe.whitelist()
def check_user_has_supplier_group_restriction():
	return _has_user_perm("Supplier Group")


@frappe.whitelist()
def check_user_has_sales_person_restriction():
	return _has_user_perm("Sales Person")


@frappe.whitelist()
def check_user_has_company_restriction():
	return _has_user_perm("Company")


@frappe.whitelist()
def check_user_has_any_restriction():
	"""Single call to check ALL restriction types at once."""
	user = frappe.session.user
	if user == "Administrator":
		return False
	perms = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabUser Permission` WHERE user=%s LIMIT 1",
		user,
	)
	return bool(perms and perms[0][0] > 0)


@frappe.whitelist()
def get_permitted_doc_preview(doctype, docname):
	"""Return document data filtered to only items the current user has permission for.

	Checks Brand, Item Group, Customer Group, Supplier Group, and Sales Person restrictions.
	"""
	user = frappe.session.user
	if user == "Administrator":
		return {"full_access": True}

	brand_perms = _get_user_brands(user)
	item_group_perms = _get_user_item_groups(user)
	cg_perms = _get_user_customer_groups(user)
	sg_perms = _get_user_supplier_groups(user)
	sp_perms = _get_user_sales_persons(user)
	company_perms = _get_user_companies(user)

	# No restrictions at all
	if not brand_perms and not item_group_perms and not cg_perms and not sg_perms and not sp_perms and not company_perms:
		return {"full_access": True}

	# Validate doctype is one we support
	child_dt = BRAND_DOCTYPES.get(doctype) or ITEM_GROUP_DOCTYPES.get(doctype)
	is_parent_brand = doctype in BRAND_PARENT_DOCTYPES
	is_parent_item_group = doctype in ITEM_GROUP_PARENT_DOCTYPES
	has_customer_group = doctype in CUSTOMER_GROUP_PARENT_DOCTYPES
	has_supplier_group = doctype in SUPPLIER_GROUP_PARENT_DOCTYPES
	has_sales_team = doctype in SALES_PERSON_DOCTYPES

	if not child_dt and not is_parent_brand and not is_parent_item_group and not has_customer_group and not has_supplier_group and not has_sales_team:
		return {"full_access": True}

	# Verify user has basic read permission on the doctype
	if not frappe.has_permission(doctype, "read"):
		return {
			"full_access": False,
			"restricted": True,
			"message": _("You do not have read permission for {0}").format(_(doctype)),
		}

	# Use ignore_permissions to bypass Frappe's built-in child-table permission
	# checks (Brand/Item Group on child items). We do our own filtering below.
	try:
		frappe.flags.ignore_permissions = True
		doc = frappe.get_doc(doctype, docname)
	finally:
		frappe.flags.ignore_permissions = False

	# Check document-level restrictions (Company, Customer Group, Supplier Group, Sales Person)
	blocked = []
	if company_perms:
		doc_company = doc.get("company") or ""
		if doc_company and doc_company not in company_perms:
			blocked.append(_("Company '{0}'").format(doc_company))
	if cg_perms and has_customer_group:
		doc_cg = doc.get("customer_group") or ""
		if doc_cg and doc_cg not in cg_perms:
			blocked.append(_("Customer Group '{0}'").format(doc_cg))
	if sg_perms and has_supplier_group:
		doc_sg = doc.get("supplier_group") or ""
		if doc_sg and doc_sg not in sg_perms:
			blocked.append(_("Supplier Group '{0}'").format(doc_sg))
	if sp_perms and has_sales_team:
		sales_team = [st.sales_person for st in (doc.get("sales_team") or []) if st.sales_person]
		if sales_team and not set(sales_team) & set(sp_perms):
			blocked.append(_("Sales Person"))
	# Sales Person as parent-level Link field
	if sp_perms and doctype in SALES_PERSON_PARENT_DOCTYPES:
		doc_sp = doc.get("sales_person") or ""
		if doc_sp and doc_sp not in sp_perms:
			blocked.append(_("Sales Person '{0}'").format(doc_sp))

	if blocked:
		return {
			"full_access": False,
			"doc_name": doc.name,
			"doctype": doctype,
			"restricted": True,
			"message": _("You do not have permission to access {0}").format(", ".join(blocked)),
		}

	# Handle parent-level doctypes (Item, Serial No, Item Price)
	if is_parent_brand or is_parent_item_group:
		parent_blocked = []
		if brand_perms and is_parent_brand:
			doc_brand = doc.get("brand") or ""
			if doc_brand and doc_brand not in brand_perms:
				parent_blocked.append(_("Brand '{0}'").format(doc_brand))
		if item_group_perms and is_parent_item_group:
			doc_ig = doc.get("item_group") or ""
			if doc_ig and doc_ig not in item_group_perms:
				parent_blocked.append(_("Item Group '{0}'").format(doc_ig))
		if parent_blocked:
			return {
				"full_access": False,
				"doc_name": doc.name,
				"doctype": doctype,
				"restricted": True,
				"message": _("You do not have permission to access {0}").format(", ".join(parent_blocked)),
			}
		if not child_dt:
			return {"full_access": True}

	# Handle child-item doctypes (skip if no child table)
	if not child_dt:
		return {"full_access": True}

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

		# Strict AND logic: item must match ALL active restrictions, blank = hidden
		brand_ok = not brand_perms or (item_brand and item_brand in brand_perms)
		ig_ok = not item_group_perms or (item_ig and item_ig in item_group_perms)
		item_ok = brand_ok and ig_ok

		if item_ok:
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
		"AND qi.brand IN ({brands})"
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
			"{child}.`brand` IN ({brands})".format(
				child=child_table, brands=brands_sql
			)
		)

	# Filter Brand Summary child table rows in report view (Quotation only)
	brand_summary_table = "`tabQuotation Brand Summary`"
	if parent_dt == "Quotation" and brand_summary_table in fields_str:
		conditions.append(
			"{bs}.`brand` IN ({brands})".format(
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
	return "{parent}.`brand` IN ({brands})".format(
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
		"AND qi.item_group IN ({igs})"
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
		return "{exists} AND {child}.`item_group` IN ({igs})".format(
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

	return "{parent}.`item_group` IN ({igs})".format(
		parent=parent_table, igs=igs_sql
	)


# ── Customer Group permission query generators ──

def _customer_group_permission_query(user, parent_dt):
	"""Permission query for doctypes where customer_group is on the parent."""
	if user == "Administrator":
		return ""

	cg_perms = _get_user_customer_groups(user)
	if not cg_perms:
		return ""

	cgs_sql = ", ".join(frappe.db.escape(cg) for cg in cg_perms)
	parent_table = "`tab{}`".format(parent_dt)

	return "{parent}.`customer_group` IN ({cgs})".format(
		parent=parent_table, cgs=cgs_sql
	)


# ── Supplier Group permission query generators ──

def _supplier_group_permission_query(user, parent_dt):
	"""Permission query for doctypes where supplier_group is on the parent."""
	if user == "Administrator":
		return ""

	sg_perms = _get_user_supplier_groups(user)
	if not sg_perms:
		return ""

	sgs_sql = ", ".join(frappe.db.escape(sg) for sg in sg_perms)
	parent_table = "`tab{}`".format(parent_dt)

	return "{parent}.`supplier_group` IN ({sgs})".format(
		parent=parent_table, sgs=sgs_sql
	)


# ── Sales Person permission query generators ──

def _sales_person_permission_query(user, parent_dt):
	"""Permission query for doctypes with Sales Team child table."""
	if user == "Administrator":
		return ""

	sp_perms = _get_user_sales_persons(user)
	if not sp_perms:
		return ""

	sps_sql = ", ".join(frappe.db.escape(sp) for sp in sp_perms)
	parent_table = "`tab{}`".format(parent_dt)

	# Strict: only show documents that have at least one matching sales person
	return (
		"EXISTS ("
		"SELECT 1 FROM `tabSales Team` st "
		"WHERE st.parent = {parent}.name "
		"AND st.parenttype = '{parent_dt}' "
		"AND st.sales_person IN ({sps})"
		")"
	).format(parent=parent_table, parent_dt=parent_dt, sps=sps_sql)


def _sales_person_parent_permission_query(user, parent_dt):
	"""Permission query for doctypes where sales_person is a parent-level Link field."""
	if user == "Administrator":
		return ""

	sp_perms = _get_user_sales_persons(user)
	if not sp_perms:
		return ""

	sps_sql = ", ".join(frappe.db.escape(sp) for sp in sp_perms)
	parent_table = "`tab{}`".format(parent_dt)

	return "{parent}.`sales_person` IN ({sps})".format(
		parent=parent_table, sps=sps_sql
	)


def _company_permission_query(user, parent_dt):
	"""Permission query for Company restriction. Dynamically checks if the doctype has a company field."""
	if user == "Administrator":
		return ""

	company_perms = _get_user_companies(user)
	if not company_perms:
		return ""

	# Check if the doctype has a company field
	meta = frappe.get_meta(parent_dt)
	if not meta.has_field("company"):
		return ""

	companies_sql = ", ".join(frappe.db.escape(c) for c in company_perms)
	parent_table = "`tab{}`".format(parent_dt)

	return "{parent}.`company` IN ({companies})".format(
		parent=parent_table, companies=companies_sql
	)


# ── Combined permission query (brand + item group) for each doctype ──

def _combined_permission_query(user, parent_dt, child_dt):
	"""Combine all permission queries for a child-item doctype.

	Brand + Item Group use AND logic (item must match BOTH brand AND item group).
	Customer Group, Supplier Group, Sales Person also use AND.
	"""
	# Item-level filters: Brand AND Item Group
	doc_parts = []
	brand_cond = _brand_permission_query(user, parent_dt, child_dt)
	if brand_cond:
		doc_parts.append(brand_cond)
	ig_cond = _item_group_permission_query(user, parent_dt, child_dt)
	if ig_cond:
		doc_parts.append(ig_cond)

	# Customer Group (parent-level field)
	if parent_dt in CUSTOMER_GROUP_PARENT_DOCTYPES:
		cg_cond = _customer_group_permission_query(user, parent_dt)
		if cg_cond:
			doc_parts.append(cg_cond)
	# Supplier Group (parent-level field)
	if parent_dt in SUPPLIER_GROUP_PARENT_DOCTYPES:
		sg_cond = _supplier_group_permission_query(user, parent_dt)
		if sg_cond:
			doc_parts.append(sg_cond)
	# Sales Person (Sales Team child table)
	if parent_dt in SALES_PERSON_DOCTYPES:
		sp_cond = _sales_person_permission_query(user, parent_dt)
		if sp_cond:
			doc_parts.append(sp_cond)
	# Sales Person (parent-level Link field)
	if parent_dt in SALES_PERSON_PARENT_DOCTYPES:
		sp_parent_cond = _sales_person_parent_permission_query(user, parent_dt)
		if sp_parent_cond:
			doc_parts.append(sp_parent_cond)
	# Company (dynamic — applies if doctype has company field and user has Company perms)
	company_cond = _company_permission_query(user, parent_dt)
	if company_cond:
		doc_parts.append(company_cond)
	return " AND ".join(doc_parts)


def _combined_parent_permission_query(user, parent_dt):
	"""Combine all permission queries for a parent-level doctype.

	Brand + Item Group use OR logic (matches EITHER).
	Other restrictions use AND.
	"""
	# Item-level: Brand OR Item Group
	item_parts = []
	if parent_dt in BRAND_PARENT_DOCTYPES:
		brand_cond = _brand_parent_permission_query(user, parent_dt)
		if brand_cond:
			item_parts.append(brand_cond)
	if parent_dt in ITEM_GROUP_PARENT_DOCTYPES:
		ig_cond = _item_group_parent_permission_query(user, parent_dt)
		if ig_cond:
			item_parts.append(ig_cond)

	parts = []
	for p in item_parts:
		parts.append(p)
	if parent_dt in CUSTOMER_GROUP_PARENT_DOCTYPES:
		cg_cond = _customer_group_permission_query(user, parent_dt)
		if cg_cond:
			parts.append(cg_cond)
	if parent_dt in SUPPLIER_GROUP_PARENT_DOCTYPES:
		sg_cond = _supplier_group_permission_query(user, parent_dt)
		if sg_cond:
			parts.append(sg_cond)
	if parent_dt in SALES_PERSON_DOCTYPES:
		sp_cond = _sales_person_permission_query(user, parent_dt)
		if sp_cond:
			parts.append(sp_cond)
	if parent_dt in SALES_PERSON_PARENT_DOCTYPES:
		sp_parent_cond = _sales_person_parent_permission_query(user, parent_dt)
		if sp_parent_cond:
			parts.append(sp_parent_cond)
	# Company (dynamic)
	company_cond = _company_permission_query(user, parent_dt)
	if company_cond:
		parts.append(company_cond)
	return " AND ".join(parts)


# ── has_permission hook ──
# Frappe's permission_query_conditions is ORed with owner/shared docs,
# so owned/shared docs bypass our filters. This hook enforces the
# restriction even for owned/shared documents.

def has_permission_check(doc, ptype, user):
	"""has_permission hook for child-item doctypes.

	Returns False if the document's items don't match the user's
	Brand/Item Group restrictions. Returns None (defer to Frappe)
	for users without restrictions or for non-read operations.
	"""
	if ptype not in ("read", "select", "export", "print", "email"):
		return None  # Only restrict read-like operations

	if user == "Administrator":
		return None

	brand_perms = _get_user_brands(user)
	ig_perms = _get_user_item_groups(user)
	cg_perms = _get_user_customer_groups(user)
	sp_perms = _get_user_sales_persons(user)
	company_perms = _get_user_companies(user)

	if not brand_perms and not ig_perms and not cg_perms and not sp_perms and not company_perms:
		return None  # No restrictions

	doctype = doc.doctype if hasattr(doc, "doctype") else doc.get("doctype")
	if not doctype:
		return None

	# Check Company (parent-level)
	if company_perms:
		doc_company = doc.get("company") or ""
		if doc_company and doc_company not in company_perms:
			return False

	# Check Customer Group (parent-level)
	if cg_perms and doctype in CUSTOMER_GROUP_PARENT_DOCTYPES:
		doc_cg = doc.get("customer_group") or ""
		if doc_cg and doc_cg not in cg_perms:
			return False

	# Check Sales Person (Sales Team child table)
	if sp_perms and doctype in SALES_PERSON_DOCTYPES:
		sales_team = [st.sales_person for st in (doc.get("sales_team") or []) if st.sales_person]
		if sales_team and not set(sales_team) & set(sp_perms):
			return False

	# Check Sales Person (parent-level Link field)
	if sp_perms and doctype in SALES_PERSON_PARENT_DOCTYPES:
		doc_sp = doc.get("sales_person") or ""
		if doc_sp and doc_sp not in sp_perms:
			return False

	# Check child item Brand and Item Group using direct SQL
	# (avoid loading child items via doc.get() which triggers Frappe's
	# built-in User Permission check on each child row)
	child_dt = BRAND_DOCTYPES.get(doctype) or ITEM_GROUP_DOCTYPES.get(doctype)
	docname = doc.name if hasattr(doc, "name") else doc.get("name")
	if child_dt and docname and (brand_perms or ig_perms):
		child_items = frappe.db.sql(
			"SELECT brand, item_group FROM `tab{dt}` WHERE parent = %s".format(dt=child_dt),
			docname,
			as_dict=True,
		)
		if child_items:
			has_brand_match = not brand_perms
			has_ig_match = not ig_perms

			for item in child_items:
				item_brand = item.get("brand") or ""
				item_ig = item.get("item_group") or ""
				if brand_perms and item_brand and item_brand in brand_perms:
					has_brand_match = True
				if ig_perms and item_ig and item_ig in ig_perms:
					has_ig_match = True

			if brand_perms and ig_perms:
				if not has_brand_match and not has_ig_match:
					return False
			else:
				if not has_brand_match or not has_ig_match:
					return False

	return True  # Explicitly allow — our permission_query_conditions already filtered the list


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

def customer_permission_query(user):
	"""Permission query for Customer.

	Users with Sales Person restriction can see:
	  1. Customers assigned to their sales person(s)
	  2. Customers with NO Sales Team at all (unassigned)
	Other restrictions (Customer Group, Company) apply with AND logic.
	"""
	if user == "Administrator":
		return ""

	parts = []

	# Customer Group filter
	cg_perms = _get_user_customer_groups(user)
	if cg_perms:
		cgs_sql = ", ".join(frappe.db.escape(cg) for cg in cg_perms)
		parts.append("`tabCustomer`.`customer_group` IN ({cgs})".format(cgs=cgs_sql))

	# Sales Person filter — include customers with matching SP OR no Sales Team
	sp_perms = _get_user_sales_persons(user)
	if sp_perms:
		sps_sql = ", ".join(frappe.db.escape(sp) for sp in sp_perms)
		parts.append(
			"("
			"EXISTS ("
			"SELECT 1 FROM `tabSales Team` st "
			"WHERE st.parent = `tabCustomer`.name "
			"AND st.parenttype = 'Customer' "
			"AND st.sales_person IN ({sps})"
			") OR NOT EXISTS ("
			"SELECT 1 FROM `tabSales Team` st2 "
			"WHERE st2.parent = `tabCustomer`.name "
			"AND st2.parenttype = 'Customer'"
			")"
			")".format(sps=sps_sql)
		)

	# Company filter — also allow customers with empty company (e.g. inter-company customers)
	company_perms = _get_user_companies(user)
	if company_perms:
		companies_sql = ", ".join(frappe.db.escape(c) for c in company_perms)
		parts.append(
			"(`tabCustomer`.`company` IN ({companies}) "
			"OR `tabCustomer`.`company` = '' "
			"OR `tabCustomer`.`company` IS NULL)".format(companies=companies_sql)
		)

	return " AND ".join(parts)


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


@frappe.whitelist()
def get_permitted_customer_groups():
	"""Return the list of permitted customer groups for the current user."""
	user = frappe.session.user
	if user == "Administrator":
		return []
	return _get_user_customer_groups(user)


@frappe.whitelist()
def get_permitted_supplier_groups():
	"""Return the list of permitted supplier groups for the current user."""
	user = frappe.session.user
	if user == "Administrator":
		return []
	return _get_user_supplier_groups(user)


@frappe.whitelist()
def get_permitted_sales_persons():
	"""Return the list of permitted sales persons for the current user."""
	user = frappe.session.user
	if user == "Administrator":
		return []
	return _get_user_sales_persons(user)


@frappe.whitelist()
def get_user_restrictions():
	"""Return all restriction lists for the current user in a single call.
	Used by form-level set_query filters to restrict link field options.
	"""
	user = frappe.session.user
	if user == "Administrator":
		return {}
	return {
		"brands": _get_user_brands(user),
		"item_groups": _get_user_item_groups(user),
		"customer_groups": _get_user_customer_groups(user),
		"supplier_groups": _get_user_supplier_groups(user),
		"sales_persons": _get_user_sales_persons(user),
	}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_filtered_customers(doctype, txt, searchfield, start, page_len, filters):
	"""Return customers filtered by Customer Group + Sales Person restrictions.

	Customers must satisfy BOTH:
	  - Customer Group in user's permitted groups (if restricted)
	  - Sales Team child table has at least one permitted Sales Person (if restricted)
	"""
	user = frappe.session.user
	cg_perms = _get_user_customer_groups(user)
	sp_perms = _get_user_sales_persons(user)
	company = filters.get("company") if isinstance(filters, dict) else None

	conditions = []
	values = {}

	if txt:
		conditions.append(
			"(c.name LIKE %(txt)s OR c.customer_name LIKE %(txt)s)"
		)
		values["txt"] = f"%{txt}%"

	if company:
		conditions.append("c.company = %(company)s")
		values["company"] = company

	if cg_perms:
		cg_list = ", ".join(frappe.db.escape(cg) for cg in cg_perms)
		conditions.append(f"c.customer_group IN ({cg_list})")

	if sp_perms:
		sp_list = ", ".join(frappe.db.escape(sp) for sp in sp_perms)
		conditions.append(
			f"EXISTS (SELECT 1 FROM `tabSales Team` st "
			f"WHERE st.parent = c.name AND st.parenttype = 'Customer' "
			f"AND st.sales_person IN ({sp_list}))"
		)

	where = " AND ".join(conditions) if conditions else "1=1"
	values["start"] = int(start)
	values["page_len"] = int(page_len)

	return frappe.db.sql(
		f"""SELECT c.name, c.customer_name, c.customer_group
		FROM `tabCustomer` c
		WHERE {where} AND c.disabled = 0
		ORDER BY c.customer_name
		LIMIT %(start)s, %(page_len)s""",
		values,
	)


# ── Export restriction ──

# All doctypes where export should be blocked for restricted users
# Additional doctypes that need export restriction (no child-item brand/ig filter,
# but need Company-based export handling to bypass export=0 role permissions)
COMPANY_ONLY_EXPORT_DOCTYPES = ["Payment Entry", "Journal Entry"]

EXPORT_RESTRICTED_DOCTYPES = set(
	list(BRAND_DOCTYPES.keys()) + BRAND_PARENT_DOCTYPES +
	list(ITEM_GROUP_DOCTYPES.keys()) + ITEM_GROUP_PARENT_DOCTYPES +
	CUSTOMER_GROUP_PARENT_DOCTYPES + SUPPLIER_GROUP_PARENT_DOCTYPES +
	SALES_PERSON_DOCTYPES + SALES_PERSON_PARENT_DOCTYPES +
	COMPANY_ONLY_EXPORT_DOCTYPES
)


@frappe.whitelist()
def restricted_export_query():
	"""Override frappe.desk.reportview.export_query.

	For restricted users on restricted doctypes, automatically route to
	filtered export (export_my_data) instead of blocking, because Frappe's
	standard export includes ALL child rows without child-level filtering.
	Unrestricted users get the standard export.
	"""
	from frappe.desk.reportview import export_query as original_export

	user = frappe.session.user
	if user != "Administrator":
		doctype = frappe.form_dict.get("doctype")
		if doctype and doctype in EXPORT_RESTRICTED_DOCTYPES:
			# Check ALL restriction types — read permissions fresh from DB every time
			has_restriction = (
				_get_user_brands(user)
				or _get_user_item_groups(user)
				or _get_user_customer_groups(user)
				or _get_user_supplier_groups(user)
				or _get_user_sales_persons(user)
				or _get_user_companies(user)
			)
			if has_restriction:
				import json as _json
				file_type = frappe.form_dict.get("file_format_type", "CSV")

				# Extract selected docnames from filters (Report View sends name IN [...])
				docnames = None
				raw_filters = frappe.form_dict.get("filters")
				if raw_filters:
					if isinstance(raw_filters, str):
						try:
							raw_filters = _json.loads(raw_filters)
						except Exception:
							raw_filters = []
					if isinstance(raw_filters, (list, tuple)):
						for f in raw_filters:
							if isinstance(f, (list, tuple)) and len(f) >= 3:
								# Frappe sends [doctype, field, op, value] or [doctype, field, op, value, hidden]
								fieldname = f[1] if len(f) >= 4 else f[0]
								operator = f[2] if len(f) >= 4 else f[1]
								value = f[3] if len(f) >= 4 else f[2]
								if fieldname == "name" and str(operator).lower() == "in":
									if isinstance(value, str):
										docnames = _json.dumps([v.strip() for v in value.split(",") if v.strip()])
									elif isinstance(value, (list, tuple)):
										docnames = _json.dumps(list(value))

				# Extract picked columns from form_dict fields
				# Frappe sends fields as: ["`tabSales Order`.`customer`", ...]
				parent_fields = None
				child_fields = None
				raw_fields = frappe.form_dict.get("fields")
				if raw_fields:
					if isinstance(raw_fields, str):
						try:
							raw_fields = _json.loads(raw_fields)
						except Exception:
							raw_fields = []
					if isinstance(raw_fields, (list, tuple)):
						import re
						pf = []
						cf = []
						child_dt = BRAND_DOCTYPES.get(doctype) or ITEM_GROUP_DOCTYPES.get(doctype)
						for f in raw_fields:
							# Parse "`tabDocType`.`fieldname`" or "tabDocType.fieldname"
							match = re.match(r"`?tab([^`]+)`?\s*\.\s*`?([^`]+)`?", str(f).strip())
							if not match:
								continue
							dt_name = match.group(1).strip()
							fn = match.group(2).strip()
							if not fn:
								continue
							if dt_name == doctype:
								pf.append(fn)
							elif child_dt and dt_name == child_dt:
								cf.append(fn)
						parent_fields = _json.dumps(pf) if pf else None
						child_fields = _json.dumps(cf) if cf else None

				return export_my_data(
					doctype=doctype,
					file_type=file_type,
					docnames=docnames,
					parent_fields_json=parent_fields,
					child_fields_json=child_fields,
				)

	return original_export()


@frappe.whitelist()
def restricted_download_template(
	doctype=None, export_fields=None, export_records=None,
	export_filters=None, file_type="CSV",
):
	"""Override frappe.core.doctype.data_import.data_import.download_template.

	For restricted users on restricted doctypes, automatically route to
	filtered export instead of blocking.
	"""
	from frappe.core.doctype.data_import.data_import import download_template as original_download

	user = frappe.session.user
	if user != "Administrator" and doctype and doctype in EXPORT_RESTRICTED_DOCTYPES:
		# Check ALL restriction types — read permissions fresh from DB every time
		has_restriction = (
			_get_user_brands(user)
			or _get_user_item_groups(user)
			or _get_user_customer_groups(user)
			or _get_user_supplier_groups(user)
			or _get_user_sales_persons(user)
			or _get_user_companies(user)
		)
		if has_restriction:
			import json as _json
			# Parse export_fields: {"Sales Order": ["customer"], "Sales Order Item": ["item_code"]}
			parent_fields = None
			child_fields = None
			if export_fields:
				if isinstance(export_fields, str):
					try:
						export_fields = _json.loads(export_fields)
					except Exception:
						export_fields = {}
				if isinstance(export_fields, dict):
					pf = export_fields.get(doctype, [])
					if pf:
						parent_fields = _json.dumps(pf)
					# Find child table fields — Frappe uses the table fieldname
					# (e.g. "items") as key, not the child doctype name
					child_dt = BRAND_DOCTYPES.get(doctype) or ITEM_GROUP_DOCTYPES.get(doctype)
					if child_dt:
						cf = export_fields.get(child_dt, [])
						# Also check by table fieldname (Frappe's Export Data dialog uses this)
						if not cf:
							meta = frappe.get_meta(doctype)
							for tf in meta.get("fields", {"fieldtype": "Table"}):
								if tf.fieldtype == "Table" and tf.options == child_dt:
									cf = export_fields.get(tf.fieldname, [])
									break
						if cf:
							child_fields = _json.dumps(cf)

			# Parse export_filters for selected docnames
			# Frappe sends: [["Sales Order","name","in",["SO-1","SO-2"]]]
			docnames = None
			if export_filters:
				if isinstance(export_filters, str):
					try:
						export_filters = _json.loads(export_filters)
					except Exception:
						export_filters = []
				if isinstance(export_filters, (list, tuple)):
					for f in export_filters:
						if isinstance(f, (list, tuple)) and len(f) >= 3:
							# Frappe sends [doctype, field, op, value] or [doctype, field, op, value, hidden]
							fieldname = f[1] if len(f) >= 4 else f[0]
							operator = f[2] if len(f) >= 4 else f[1]
							value = f[3] if len(f) >= 4 else f[2]
							if fieldname == "name" and str(operator).lower() == "in":
								if isinstance(value, str):
									docnames = _json.dumps([v.strip() for v in value.split(",") if v.strip()])
								elif isinstance(value, (list, tuple)):
									docnames = _json.dumps(list(value))
				elif isinstance(export_filters, dict) and export_filters.get("name"):
					names = export_filters["name"]
					if isinstance(names, (list, tuple)):
						docnames = _json.dumps(list(names))

			return export_my_data(
				doctype=doctype,
				file_type=file_type,
				docnames=docnames,
				parent_fields_json=parent_fields,
				child_fields_json=child_fields,
			)

	return original_download(
		doctype=doctype,
		export_fields=export_fields,
		export_records=export_records,
		export_filters=export_filters,
		file_type=file_type,
	)

# ── Script Report filter injection ──

# Reports that have brand/item_group filters
BRAND_FILTER_REPORTS = [
	"Stock Balance", "Stock Ledger", "Stock Projected Qty", "Stock Analytics",
	"Stock Ageing", "Warehouse Wise Item Balance Age and Value",
	"Item Price Stock", "Item Prices", "Itemwise Recommended Reorder Level",
	"Product Bundle Balance", "Sales Person-wise Transaction Summary",
	"Sales Partner Transaction Summary", "Gross Profit",
	"Item-wise Sales Register",
]


@frappe.whitelist()
def restricted_query_report_run(
	report_name=None, filters=None, page_length=None, are_default_filters=None,
	is_custom_report=None, custom_columns=None, user=None,
):
	"""Override frappe.desk.query_report.run to inject Brand/Item Group filters
	for restricted users into Script Reports.
	"""
	from frappe.desk.query_report import run as original_run
	import json

	current_user = frappe.session.user
	if current_user == "Administrator":
		return original_run(
			report_name=report_name, filters=filters, page_length=page_length,
			are_default_filters=are_default_filters, is_custom_report=is_custom_report,
			custom_columns=custom_columns, user=user,
		)

	# Parse filters
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except Exception:
			filters = {}
	if not filters:
		filters = {}

	# Inject brand filter for restricted users
	brand_perms = _get_user_brands(current_user)
	if brand_perms and report_name in BRAND_FILTER_REPORTS:
		if not filters.get("brand"):
			if len(brand_perms) == 1:
				filters["brand"] = brand_perms[0]
			# For multiple brands, the report only supports single brand filter
			# Force the first one to ensure filtering
			else:
				filters["brand"] = brand_perms[0]

	# Inject item_group filter
	ig_perms = _get_user_item_groups(current_user)
	if ig_perms and report_name in BRAND_FILTER_REPORTS:
		if not filters.get("item_group"):
			if len(ig_perms) == 1:
				filters["item_group"] = ig_perms[0]

	return original_run(
		report_name=report_name, filters=json.dumps(filters), page_length=page_length,
		are_default_filters=are_default_filters, is_custom_report=is_custom_report,
		custom_columns=custom_columns, user=user,
	)


# ── Custom filtered export for restricted users ──

@frappe.whitelist()
def export_my_data(doctype, file_type="CSV", docnames=None, parent_fields_json=None, child_fields_json=None):
	"""Export only the user's permitted data with dynamic child-row filtering.

	Dynamically reads ALL User Permissions for the current user and filters
	child rows by ANY matching field (brand, item_group, etc.) using AND logic.
	If docnames is provided, only those specific documents are exported.
	If parent_fields_json/child_fields_json provided, use those columns instead of defaults.
	"""
	import csv
	import io
	import json as json_mod

	user = frappe.session.user
	if user == "Administrator":
		frappe.throw(_("Administrators should use the standard Export."))

	if doctype not in EXPORT_RESTRICTED_DOCTYPES:
		frappe.throw(_("This doctype does not require filtered export."))

	# Parse selected docnames if provided
	selected_names = None
	if docnames:
		if isinstance(docnames, str):
			selected_names = json_mod.loads(docnames)
		else:
			selected_names = list(docnames)

	# ── Dynamically read ALL User Permissions ──
	all_perms = frappe.db.sql(
		"SELECT allow, for_value FROM `tabUser Permission` WHERE user=%s",
		user, as_dict=True,
	)
	if not all_perms:
		frappe.throw(
			_("You have no data restrictions. Please use the standard Export instead."),
			title=_("No Restrictions"),
		)

	# Group by allow type: {"Brand": ["Yealink"], "Item Group": ["UC Product"], ...}
	perm_map = {}
	for p in all_perms:
		perm_map.setdefault(p["allow"], []).append(p["for_value"])

	meta = frappe.get_meta(doctype)

	# Parse custom field lists if provided (from Report View Pick Columns)
	custom_parent_fields = None
	custom_child_fields = None
	if parent_fields_json:
		custom_parent_fields = json_mod.loads(parent_fields_json) if isinstance(parent_fields_json, str) else list(parent_fields_json)
	if child_fields_json:
		custom_child_fields = json_mod.loads(child_fields_json) if isinstance(child_fields_json, str) else list(child_fields_json)

	# Build parent fields list — query actual DB columns (only reliable method)
	db_columns = set(frappe.db.sql(
		"SELECT column_name FROM information_schema.columns WHERE table_name=%s",
		f"tab{doctype}", pluck="column_name",
	))
	if custom_parent_fields:
		parent_fields = ["name"] + [fn for fn in custom_parent_fields if fn != "name" and fn in db_columns]
	else:
		parent_fields = ["name"]
		for fn in ["customer", "customer_name", "supplier", "supplier_name", "party_name",
				   "transaction_date", "posting_date", "grand_total", "status",
				   "company", "currency", "customer_group", "sales_person"]:
			if meta.has_field(fn):
				parent_fields.append(fn)

	# Build permission query for parent docs (uses all restriction types)
	child_dt_for_query = BRAND_DOCTYPES.get(doctype) or ITEM_GROUP_DOCTYPES.get(doctype)
	if child_dt_for_query:
		perm_cond = _combined_permission_query(user, doctype, child_dt_for_query)
	else:
		perm_cond = ""

	if perm_cond:
		sql = "SELECT name FROM `tab{dt}` WHERE {cond}".format(dt=doctype, cond=perm_cond)
		# If specific docs selected, intersect with permission query
		if selected_names:
			ph = ", ".join(["%s"] * len(selected_names))
			sql += " AND name IN ({ph})".format(ph=ph)
			parent_names = frappe.db.sql(sql + " ORDER BY modified DESC LIMIT 5000", selected_names, pluck="name")
		else:
			parent_names = frappe.db.sql(sql + " ORDER BY modified DESC LIMIT 5000", pluck="name")
	else:
		filters = {}
		if selected_names:
			filters["name"] = ["in", selected_names]
		parent_names = frappe.get_list(
			doctype, fields=["name"], filters=filters,
			limit_page_length=5000, order_by="modified desc", pluck="name",
		)

	if not parent_names:
		frappe.respond_as_web_page(
			_("No Data"),
			_("No {0} records found matching your permissions.").format(_(doctype)),
			http_status_code=200, indicator_color="orange",
		)
		return

	# Get child table
	child_dt = BRAND_DOCTYPES.get(doctype) or ITEM_GROUP_DOCTYPES.get(doctype)
	if not child_dt:
		# Parent-level doctype (Item, Serial No, etc.) - export directly
		output = io.StringIO()
		writer = csv.writer(output)
		header_labels = [meta.get_field(fn).label if meta.get_field(fn) else fn for fn in parent_fields]
		writer.writerow(header_labels)
		for name in parent_names:
			row_data = frappe.db.get_value(doctype, name, parent_fields, as_dict=True)
			writer.writerow([row_data.get(fn, "") for fn in parent_fields])
		_send_csv_response(output.getvalue(), doctype, file_type)
		return

	# ── Build dynamic child-row filter map ──
	# Map User Permission type → child table fieldname
	# e.g. {"Brand": "brand", "Item Group": "item_group"}
	child_meta = frappe.get_meta(child_dt)
	child_filter_map = {}  # {fieldname: [permitted_values]}
	for allow_type, values in perm_map.items():
		fieldname = frappe.scrub(allow_type)  # "Brand" → "brand", "Item Group" → "item_group"
		if child_meta.has_field(fieldname):
			child_filter_map[fieldname] = set(values)

	# Fetch child table fields — query actual DB columns (only reliable method)
	child_db_columns = set(frappe.db.sql(
		"SELECT column_name FROM information_schema.columns WHERE table_name=%s",
		f"tab{child_dt}", pluck="column_name",
	))
	if custom_child_fields:
		child_fields = ["parent", "idx"] + [fn for fn in custom_child_fields if fn not in ("parent", "idx", "name") and fn in child_db_columns]
	elif custom_parent_fields:
		# User explicitly picked parent fields but no child fields — skip child data
		child_fields = []
	else:
		child_fields = ["parent", "idx"]
		for fn in ["item_code", "item_name", "brand", "item_group", "qty", "rate",
				   "amount", "uom", "description", "warehouse"]:
			if child_meta.has_field(fn):
				child_fields.append(fn)

	# If no child fields selected, export parent-only (one row per document)
	if not child_fields:
		def _get_label_p(fieldname):
			df = meta.get_field(fieldname)
			return df.label if df else fieldname
		output = io.StringIO()
		writer = csv.writer(output)
		header = [_get_label_p("name")] + [_get_label_p(fn) for fn in parent_fields if fn != "name"]
		writer.writerow(header)
		for name in parent_names:
			row_data = frappe.db.get_value(doctype, name, parent_fields, as_dict=True) or {}
			data = [name] + [str(row_data.get(fn, "")) for fn in parent_fields if fn != "name"]
			writer.writerow(data)
		_send_csv_response(output.getvalue(), doctype, file_type)
		return

	# Fetch ALL child rows for permitted parents
	# Filter by parenttype to avoid orphaned rows or rows from other parent doctypes
	all_children = []
	batch_size = 500
	for i in range(0, len(parent_names), batch_size):
		batch = parent_names[i:i + batch_size]
		ph = ", ".join(["%s"] * len(batch))
		rows = frappe.db.sql(
			"SELECT {fields} FROM `tab{dt}` WHERE parent IN ({ph}) AND parenttype=%s ORDER BY parent, idx".format(
				fields=", ".join(child_fields), dt=child_dt, ph=ph
			),
			batch + [doctype], as_dict=True,
		)
		all_children.extend(rows)

	# ── Dynamic child-row filtering: AND logic ──
	# Item must match ALL active restrictions that exist on the child table
	# Blank values are allowed through — only reject rows with a non-matching value
	filtered_children = []
	for row in all_children:
		ok = True
		for fieldname, permitted_values in child_filter_map.items():
			row_val = row.get(fieldname) or ""
			# Allow blank values (item may not have brand/item_group set)
			# Only reject if the field has a value that doesn't match
			if row_val and row_val not in permitted_values:
				ok = False
				break
		if ok:
			filtered_children.append(row)

	# Get Sales Team data (only permitted sales persons)
	sp_perms = perm_map.get("Sales Person", [])
	sales_team_data = {}
	if sp_perms and doctype in SALES_PERSON_DOCTYPES:
		for i in range(0, len(parent_names), batch_size):
			batch = parent_names[i:i + batch_size]
			ph = ", ".join(["%s"] * len(batch))
			sp_list = ", ".join(frappe.db.escape(s) for s in sp_perms)
			st_rows = frappe.db.sql(
				"SELECT parent, sales_person FROM `tabSales Team` "
				"WHERE parent IN ({ph}) AND parenttype = %s "
				"AND sales_person IN ({sp})".format(ph=ph, sp=sp_list),
				batch + [doctype], as_dict=True,
			)
			for st in st_rows:
				sales_team_data.setdefault(st.parent, []).append(st.sales_person)

	# Build parent data lookup
	parent_data = {}
	for name in parent_names:
		parent_data[name] = frappe.db.get_value(
			doctype, name, parent_fields, as_dict=True
		) or {}

	# Build label lookup for headers
	def _get_label(fieldname, dt_meta):
		df = dt_meta.get_field(fieldname)
		return df.label if df else fieldname

	# Generate CSV
	output = io.StringIO()
	writer = csv.writer(output)

	header = [_get_label("name", meta)]
	header += [_get_label(fn, meta) for fn in parent_fields if fn != "name"]
	header += [_get_label(fn, child_meta) + " (Items)" for fn in child_fields if fn not in ("parent",)]
	if sp_perms:
		header.append("Sales Person")
	writer.writerow(header)

	for row in filtered_children:
		parent = parent_data.get(row.parent, {})
		data = [row.parent]
		data += [str(parent.get(fn, "")) for fn in parent_fields if fn != "name"]
		data += [str(row.get(fn, "")) for fn in child_fields if fn not in ("parent",)]
		if sp_perms:
			data.append(", ".join(sales_team_data.get(row.parent, [])))
		writer.writerow(data)

	csv_content = output.getvalue()
	output.close()

	if not filtered_children:
		frappe.respond_as_web_page(
			_("No Data"),
			_("No items matching your permissions found in the permitted {0} records.").format(_(doctype)),
			http_status_code=200, indicator_color="orange",
		)
		return

	_send_csv_response(csv_content, doctype, file_type)


def _send_csv_response(csv_content, doctype, file_type):
	"""Helper to send CSV or Excel download response."""
	if file_type == "Excel":
		import csv as csv_mod
		from frappe.utils.xlsxutils import make_xlsx
		xlsx_data = list(csv_mod.reader(io.StringIO(csv_content)))
		xlsx_file = make_xlsx(xlsx_data, doctype)
		frappe.response["filename"] = f"{doctype}_my_data.xlsx"
		frappe.response["filecontent"] = xlsx_file.getvalue()
		frappe.response["type"] = "download"
	else:
		frappe.response["filename"] = f"{doctype}_my_data.csv"
		frappe.response["filecontent"] = csv_content
		frappe.response["type"] = "download"


# ── Monkey-patch: force permission_query_conditions on shared docs ──

_RESTRICTED_DOCTYPES = set(
	list(BRAND_DOCTYPES.keys()) + list(ITEM_GROUP_DOCTYPES.keys()) +
	CUSTOMER_GROUP_PARENT_DOCTYPES + SUPPLIER_GROUP_PARENT_DOCTYPES +
	SALES_PERSON_DOCTYPES
)


def patch_shared_document_filter():
	"""Monkey-patch DatabaseQuery.build_match_conditions so that shared
	documents also go through our permission_query_conditions.

	By default Frappe adds: (match_conds AND pq_conds) OR (name IN shared_docs)
	The shared docs OR bypass ignores our custom permission filters.

	This patch removes shared docs from the OR clause for restricted doctypes,
	forcing all documents to go through the standard permission path.
	"""
	from frappe.model.db_query import DatabaseQuery

	_original_build = DatabaseQuery.build_match_conditions

	def patched_build_match_conditions(self, as_condition=True):
		result = _original_build(self, as_condition=as_condition)

		user = self.user or frappe.session.user
		if user == "Administrator":
			return result

		# For Customer doctype: Frappe's standard match conditions filter
		# company IN (user's companies), which hides customers with empty
		# company (e.g. inter-company customers). Replace the strict company
		# filter to also allow empty company values.
		if as_condition and result and self.doctype == "Customer":
			company_perms = _get_user_companies(user)
			if company_perms:
				import re
				# Frappe generates: `tabCustomer`.`company` in ('X','Y',...)
				pattern = r"`tabCustomer`\.`company`\s+in\s+\([^)]+\)"
				replacement = (
					"(`tabCustomer`.`company` in ({cos}) "
					"OR `tabCustomer`.`company` = '' "
					"OR `tabCustomer`.`company` IS NULL)"
				).format(cos=", ".join(frappe.db.escape(c) for c in company_perms))
				result = re.sub(pattern, replacement, result)

		# For restricted doctypes, remove the shared doc OR bypass
		# Frappe generates: ((conditions) or (name in (...shared...)))
		# We strip the shared part so ALL docs must pass permission conditions
		if (
			as_condition
			and result
			and self.doctype in _RESTRICTED_DOCTYPES
			and user != "Administrator"
			and self.shared
		):
			share_cond = self.get_share_condition()
			if share_cond and share_cond in result:
				# Remove the OR (shared) wrapper
				# Result looks like: ((real_conditions) or (share_condition))
				# Strip to just: real_conditions
				result = result.replace(f" or ({share_cond})", "")
				# Clean up extra wrapper parens: ((...)) -> ...
				if result.startswith("((") and result.endswith("))"):
					result = result[1:-1]

		return result

	DatabaseQuery.build_match_conditions = patched_build_match_conditions



