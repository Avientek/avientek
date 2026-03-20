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


def _get_user_customer_groups(user=None):
	"""Get list of permitted customer groups for a user. Returns empty list if no restriction."""
	user = user or frappe.session.user
	if user == "Administrator":
		return []
	return frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Customer Group"},
		pluck="for_value",
	)


def _get_user_supplier_groups(user=None):
	"""Get list of permitted supplier groups for a user. Returns empty list if no restriction."""
	user = user or frappe.session.user
	if user == "Administrator":
		return []
	return frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Supplier Group"},
		pluck="for_value",
	)


def _get_user_sales_persons(user=None):
	"""Get list of permitted sales persons for a user. Returns empty list if no restriction."""
	user = user or frappe.session.user
	if user == "Administrator":
		return []
	return frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Sales Person"},
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
def check_user_has_customer_group_restriction():
	"""Quick check: does the current user have any Customer Group User Permissions?"""
	user = frappe.session.user
	if user == "Administrator":
		return False
	return bool(frappe.db.exists("User Permission", {"user": user, "allow": "Customer Group"}))


@frappe.whitelist()
def check_user_has_supplier_group_restriction():
	"""Quick check: does the current user have any Supplier Group User Permissions?"""
	user = frappe.session.user
	if user == "Administrator":
		return False
	return bool(frappe.db.exists("User Permission", {"user": user, "allow": "Supplier Group"}))


@frappe.whitelist()
def check_user_has_sales_person_restriction():
	"""Quick check: does the current user have any Sales Person User Permissions?"""
	user = frappe.session.user
	if user == "Administrator":
		return False
	return bool(frappe.db.exists("User Permission", {"user": user, "allow": "Sales Person"}))


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

	# No restrictions at all
	if not brand_perms and not item_group_perms and not cg_perms and not sg_perms and not sp_perms:
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

	doc = frappe.get_doc(doctype, docname)

	# Check document-level restrictions (Customer Group, Supplier Group, Sales Person)
	blocked = []
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

	return "({parent}.`customer_group` IN ({cgs}) OR IFNULL({parent}.`customer_group`, '') = '')".format(
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

	return "({parent}.`supplier_group` IN ({sgs}) OR IFNULL({parent}.`supplier_group`, '') = '')".format(
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

	# Show documents that have at least one matching sales person,
	# OR documents with no Sales Team entries (empty = visible, like brand pattern)
	return (
		"("
		"EXISTS ("
		"SELECT 1 FROM `tabSales Team` st "
		"WHERE st.parent = {parent}.name "
		"AND st.parenttype = '{parent_dt}' "
		"AND st.sales_person IN ({sps})"
		") OR NOT EXISTS ("
		"SELECT 1 FROM `tabSales Team` st2 "
		"WHERE st2.parent = {parent}.name "
		"AND st2.parenttype = '{parent_dt}'"
		")"
		")"
	).format(parent=parent_table, parent_dt=parent_dt, sps=sps_sql)


# ── Combined permission query (brand + item group) for each doctype ──

def _combined_permission_query(user, parent_dt, child_dt):
	"""Combine all permission queries for a child-item doctype."""
	parts = []
	brand_cond = _brand_permission_query(user, parent_dt, child_dt)
	if brand_cond:
		parts.append(brand_cond)
	ig_cond = _item_group_permission_query(user, parent_dt, child_dt)
	if ig_cond:
		parts.append(ig_cond)
	# Customer Group (parent-level field)
	if parent_dt in CUSTOMER_GROUP_PARENT_DOCTYPES:
		cg_cond = _customer_group_permission_query(user, parent_dt)
		if cg_cond:
			parts.append(cg_cond)
	# Supplier Group (parent-level field)
	if parent_dt in SUPPLIER_GROUP_PARENT_DOCTYPES:
		sg_cond = _supplier_group_permission_query(user, parent_dt)
		if sg_cond:
			parts.append(sg_cond)
	# Sales Person (Sales Team child table)
	if parent_dt in SALES_PERSON_DOCTYPES:
		sp_cond = _sales_person_permission_query(user, parent_dt)
		if sp_cond:
			parts.append(sp_cond)
	return " AND ".join(parts)


def _combined_parent_permission_query(user, parent_dt):
	"""Combine all permission queries for a parent-level doctype."""
	parts = []
	if parent_dt in BRAND_PARENT_DOCTYPES:
		brand_cond = _brand_parent_permission_query(user, parent_dt)
		if brand_cond:
			parts.append(brand_cond)
	if parent_dt in ITEM_GROUP_PARENT_DOCTYPES:
		ig_cond = _item_group_parent_permission_query(user, parent_dt)
		if ig_cond:
			parts.append(ig_cond)
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
