import frappe
from frappe import _


@frappe.whitelist()
def get_available_permission_managers():
	"""Get all active User Permission Managers"""
	managers = frappe.get_all("User Permission Manager",
		filters={"is_active": 1},
		fields=["name", "manager_name", "description", "user_field"],
		order_by="manager_name"
	)

	for manager in managers:
		count = frappe.db.count("User Permission Details", {"parent": manager.name})
		manager["permission_count"] = count

	return managers


@frappe.whitelist()
def get_user_permissions_summary(user_email):
	"""Get summary of user permissions with their source managers"""
	doc = frappe.new_doc("User Permission Manager")
	doc.ensure_user_permission_custom_field()

	permissions = frappe.db.sql("""
		SELECT
			up.name,
			up.allow,
			up.for_value,
			up.applicable_for,
			up.apply_to_all_doctypes,
			up.is_default,
			up.user_permission_manager,
			upm.manager_name
		FROM `tabUser Permission` up
		LEFT JOIN `tabUser Permission Manager` upm ON up.user_permission_manager = upm.name
		WHERE up.user = %s
		ORDER BY up.allow, up.for_value
	""", (user_email,), as_dict=True)

	managed_permissions = []
	manual_permissions = []

	for perm in permissions:
		if perm.user_permission_manager:
			managed_permissions.append(perm)
		else:
			manual_permissions.append(perm)

	return {
		"managed_permissions": managed_permissions,
		"manual_permissions": manual_permissions,
		"total_permissions": len(permissions)
	}


@frappe.whitelist()
def bulk_apply_permission_manager(manager_name, user_emails):
	"""Apply permission manager to multiple users"""
	if isinstance(user_emails, str):
		import json
		user_emails = json.loads(user_emails)

	if not frappe.has_permission("User Permission Manager", "write"):
		frappe.throw(_("Insufficient permissions"))

	manager_doc = frappe.get_doc("User Permission Manager", manager_name)

	if not manager_doc.is_active:
		frappe.throw(_("User Permission Manager is not active"))

	results = []

	for user_email in user_emails:
		try:
			manager_doc.create_user_permissions_for_user(user_email)
			results.append({
				"user": user_email,
				"success": True,
				"message": _("Permissions applied successfully")
			})
		except Exception as e:
			results.append({
				"user": user_email,
				"success": False,
				"message": str(e)
			})

	return {"results": results}


@frappe.whitelist()
def remove_permission_manager_from_user(manager_name, user_email):
	"""Remove all permissions created by a specific manager for a user"""
	if not frappe.has_permission("User Permission Manager", "write"):
		frappe.throw(_("Insufficient permissions"))

	doc = frappe.new_doc("User Permission Manager")
	doc.ensure_user_permission_custom_field()

	permissions_to_delete = frappe.get_all("User Permission",
		filters={
			"user": user_email,
			"user_permission_manager": manager_name
		},
		pluck="name"
	)

	deleted_count = 0
	for perm_name in permissions_to_delete:
		frappe.delete_doc("User Permission", perm_name, ignore_permissions=True)
		deleted_count += 1

	frappe.db.commit()

	return {
		"success": True,
		"message": _("Removed {0} permissions from user {1}").format(deleted_count, user_email),
		"deleted_count": deleted_count
	}


@frappe.whitelist()
def sync_all_permission_managers():
	"""Sync all active permission managers"""
	if not frappe.has_permission("User Permission Manager", "write"):
		frappe.throw(_("Insufficient permissions"))

	active_managers = frappe.get_all("User Permission Manager",
		filters={"is_active": 1},
		pluck="name"
	)

	results = []

	for manager_name in active_managers:
		try:
			manager_doc = frappe.get_doc("User Permission Manager", manager_name)
			manager_doc.sync_user_permissions()

			results.append({
				"manager": manager_name,
				"success": True,
				"message": _("Synced successfully")
			})
		except Exception as e:
			results.append({
				"manager": manager_name,
				"success": False,
				"message": str(e)
			})

	return {
		"results": results,
		"total_managers": len(active_managers),
		"success_count": len([r for r in results if r["success"]])
	}


@frappe.whitelist()
def get_permission_statistics():
	"""Get statistics about user permissions and managers"""
	stats = {}

	stats["total_managers"] = frappe.db.count("User Permission Manager")
	stats["active_managers"] = frappe.db.count("User Permission Manager", {"is_active": 1})
	stats["inactive_managers"] = stats["total_managers"] - stats["active_managers"]

	stats["total_permissions"] = frappe.db.count("User Permission")

	doc = frappe.new_doc("User Permission Manager")
	doc.ensure_user_permission_custom_field()

	managed_count = frappe.db.count("User Permission", {"user_permission_manager": ["!=", ""]})
	stats["managed_permissions"] = managed_count
	stats["manual_permissions"] = stats["total_permissions"] - managed_count

	users_with_permissions = frappe.db.sql("""
		SELECT COUNT(DISTINCT user) as count
		FROM `tabUser Permission`
	""")[0][0]
	stats["users_with_permissions"] = users_with_permissions

	common_permissions = frappe.db.sql("""
		SELECT allow, COUNT(*) as count
		FROM `tabUser Permission`
		GROUP BY allow
		ORDER BY count DESC
		LIMIT 5
	""", as_dict=True)
	stats["common_permissions"] = common_permissions

	return stats


# ────────────────────────────────────────────────────────────────────────
# CUSTOM-REPORT helpers — call these from Script Reports / Server Scripts
# in either the avientek or avientek_reports app to make raw SQL respect
# User Permissions automatically. Sridhar 2026-05-04: every custom report
# users build needs to honor User Permissions just like the built-in
# Frappe report list does.
# ────────────────────────────────────────────────────────────────────────


def get_user_permission_values(user, doctype):
	"""Return the list of `for_value` strings the user is permitted on for a
	given DocType (e.g. all Companies / Sales Persons / Item Groups they can
	see). Empty list = no User Permission set for that DocType — caller
	decides whether to interpret that as 'allow all' (typical) or 'deny all'.

	Always passes through System Manager / Administrator without filtering,
	since those roles bypass User Permissions in core Frappe.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return []  # signal: bypass — caller should treat as 'no restriction'
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles:
		return []
	return frappe.db.get_all(
		"User Permission",
		filters={"user": user, "allow": doctype},
		pluck="for_value",
	) or []


def build_permission_where_sql(alias_map, user=None, prefix="up"):
	"""Build a SQL fragment that constrains a raw query to rows the user is
	permitted to see on the given DocType columns.

	Args:
		alias_map: {DocType -> "table_alias.column"} mapping. The DocType
			key is matched against User Permission.allow; the value is the
			SQL expression in your query that holds that DocType's name
			(e.g. {"Company": "so.company", "Item Group": "i.item_group"}).
		user: defaults to frappe.session.user. System Manager / Administrator
			get an empty fragment (= no restriction).
		prefix: deduplication prefix for generated parameter names. Override
			only if you have multiple calls in one query.

	Returns:
		(where_fragment, params_dict) — fragment starts with ' AND ' so it
		is safe to splice onto a query that already has a WHERE 1=1 base, or
		strip the leading ' AND ' if your query has no WHERE at all.

		If no User Permissions apply for any of the given DocTypes (or user
		is bypass), returns ('', {}).

	Example:
		uw, up = build_permission_where_sql({
			"Company": "so.company",
			"Item Group": "i.item_group",
		})
		query = "SELECT ... FROM `tabSales Order` so JOIN `tabItem` i "
				"WHERE 1=1 " + uw
		rows = frappe.db.sql(query, {**filters, **up}, as_dict=True)
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return "", {}
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles:
		return "", {}

	clauses = []
	params = {}
	idx = 0
	for doctype, sql_expr in (alias_map or {}).items():
		values = frappe.db.get_all(
			"User Permission",
			filters={"user": user, "allow": doctype},
			pluck="for_value",
		) or []
		if not values:
			# No User Permission row → user has unrestricted view on this
			# DocType (Frappe core behaviour). Skip this dimension.
			continue
		placeholders = []
		for v in values:
			pname = f"{prefix}_p{idx}"
			placeholders.append(f"%({pname})s")
			params[pname] = v
			idx += 1
		clauses.append(f"({sql_expr}) IN ({', '.join(placeholders)})")

	if not clauses:
		return "", {}
	return " AND " + " AND ".join(clauses), params


def filter_rows_by_user_permissions(rows, field_map, user=None):
	"""Post-filter a list of dict rows by User Permissions. Use this when
	the row data is built up in Python (joins/aggregations) and pre-filtering
	via SQL is impractical.

	Args:
		rows: list of dicts.
		field_map: {DocType -> dict_key} — e.g. {"Customer": "customer",
			"Brand": "brand"}. Each row's value at dict_key is checked
			against the user's allowed values for the DocType.
		user: defaults to frappe.session.user.

	Bypasses System Manager / Administrator. DocTypes for which the user
	has no User Permission rows are not filtered (Frappe core behaviour).
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return rows
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles:
		return rows

	allow_sets = {}
	for doctype in (field_map or {}).keys():
		vals = frappe.db.get_all(
			"User Permission",
			filters={"user": user, "allow": doctype},
			pluck="for_value",
		) or []
		if vals:
			allow_sets[doctype] = set(vals)
	if not allow_sets:
		return rows

	out = []
	for r in rows:
		ok = True
		for doctype, key in field_map.items():
			allowed = allow_sets.get(doctype)
			if allowed is None:
				continue  # no UP for this DocType → don't filter
			val = r.get(key)
			if val is None or val == "":
				continue  # missing value → don't filter (let it through)
			if val not in allowed:
				ok = False
				break
		if ok:
			out.append(r)
	return out
