"""User-Permission helpers used by Avientek custom reports + the global
filter override in `restricted_query_report_run`.

The legacy User Permission Manager / User Permission Details DocTypes
were removed 2026-05-05. The whitelisted endpoints that wrapped UPM
(get_available_permission_managers, get_user_permissions_summary,
bulk_apply_permission_manager, remove_permission_manager_from_user,
sync_all_permission_managers, get_permission_statistics) are gone with
the doctypes — clients had no remaining callers, and Frappe's native
/app/user-permission UI covers the same workflow.

What's kept: the report helpers, used both directly by Avientek query
reports and indirectly by `apply_global_user_permission_filter`.
"""
import frappe


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
