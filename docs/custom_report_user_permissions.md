# Custom Reports — Respecting User Permissions

## TL;DR

If your report runs raw SQL (Script Report / Server Script / Query Report),
**Frappe does not auto-apply User Permissions for you**. You must filter
the data yourself. Use the helpers in
`avientek.api.user_permission_utils` so every report does it the same way.

| Report type | User Permissions auto-applied? | What to do |
|---|---|---|
| Report Builder (UI custom report) | Yes | Nothing — `frappe.get_list` honors them |
| Custom Report on top of a Script Report | Yes (inherits parent's filtering) | Make sure the parent filters correctly |
| Script Report (Python file) | **No** | Call the helpers below |
| Query Report (raw SQL in UI) | **No** | Call the helpers below |
| Server Script Report | **No** | Call the helpers below |

## Helpers (in `avientek/api/user_permission_utils.py`)

### `get_user_permission_values(user, doctype) -> list[str]`

Returns the list of allowed values the user has for a DocType
(e.g. all Companies / Item Groups they're permitted on). Empty list =
no User Permission rows for that DocType — caller treats as
"unrestricted" (Frappe core behaviour).

Bypasses System Manager / Administrator (returns `[]` so caller does
no filtering for them).

### `build_permission_where_sql(alias_map, user=None, prefix="up") -> (str, dict)`

Builds a SQL `AND ...` fragment + params dict to splice into a raw query.
Use this when you want pre-filtering at the database (best perf).

```python
from avientek.api.user_permission_utils import build_permission_where_sql

uw, up = build_permission_where_sql({
    "Company":    "so.company",
    "Item Group": "(SELECT item_group FROM `tabItem` WHERE name = soi.item_code)",
    "Customer":   "so.customer",
    "Brand":      "soi.brand",
    "Territory":  "so.territory",
})
query = (
    "SELECT ... FROM `tabSales Order` so "
    "JOIN `tabSales Order Item` soi ON soi.parent = so.name "
    "WHERE so.docstatus = 1 " + uw
)
rows = frappe.db.sql(query, {**filters, **up}, as_dict=True)
```

Returns `('', {})` when the user is bypass — safe to splice unconditionally.

### `filter_rows_by_user_permissions(rows, field_map, user=None) -> list[dict]`

Post-filter Python rows by User Permissions. Use this for dimensions
computed *after* the SQL (joins/aggregations) where pre-filtering is
hard.

```python
from avientek.api.user_permission_utils import filter_rows_by_user_permissions

data = filter_rows_by_user_permissions(data, {
    "Customer":  "customer",
    "Item Group": "item_group",
    "Brand":     "brand",
})
```

## Pattern for the standard "UI filter wins, otherwise fall back to User Permission"

```python
allowed = get_user_permission_values(frappe.session.user, "Item Group")
ui_value = filters.get("item_group")
if ui_value:
    cond.append("...")
    params.append(ui_value)
elif allowed:
    cond.append(f"... IN ({', '.join(['%s'] * len(allowed))})")
    params.extend(allowed)
```

This is what `avientek_stock_allocation` does for every dimension.

## What if a user creates a new Custom Report?

* If they pick **"Custom Report" from a Script Report**, the parent's
  `execute()` runs first — they automatically inherit its filtering. No
  extra work.
* If they pick **"Query Report" / "Server Script Report"**, they're
  writing raw SQL — they MUST call `build_permission_where_sql` from
  their script. Show them this doc.

## Defensive default

If you're unsure which dimensions matter, just always pass the full set
to the helper. Dimensions with no User Permission rows are silently
skipped — so it costs nothing to over-specify:

```python
ALL_DIMS = {
    "Company":    "so.company",
    "Item Group": "(SELECT item_group FROM `tabItem` WHERE name = soi.item_code)",
    "Customer":   "so.customer",
    "Brand":      "soi.brand",
    "Territory":  "so.territory",
    "Sales Person": "(SELECT sales_person FROM `tabSales Team` "
                    "WHERE parent = so.name LIMIT 1)",
}
uw, up = build_permission_where_sql(ALL_DIMS)
```

## Verifying in production

Pick a test user (e.g. `testqcs@gmail.com`) with limited permissions.
Run any custom report from their session. Confirm rows are constrained
to their allowed Companies / Item Groups / Customers / etc. If the
report's author followed the helpers, this just works.

## Global automatic filter (zero-config)

Every query report — Script Report, Server Script Report, Query Report,
Custom Report — runs through `frappe.desk.query_report.run`, which we
override with our wrapper at `avientek.api.quotation_access.restricted_query_report_run`.
After the original implementation runs, the wrapper calls
`avientek.api.report_permission_filter.apply_global_user_permission_filter`
which post-filters the rows by inspecting Link columns and the caller's
User Permissions.

What this means:

* **A user can create a brand-new Custom Report and forget about User
  Permissions.** Rows are still trimmed to their allowed values for
  any Link column that points to a constrained DocType.
* The set of constrained DocTypes is `DEFAULT_FILTERED_DOCTYPES` in
  `avientek/api/report_permission_filter.py`. Default list:
  Company, Sales Person, Item Group, Customer, Brand, Territory,
  Warehouse, Cost Center, Project, Department, Employee.
* System Manager and Administrator are bypassed (Frappe convention).

### Limitations of the global filter

The global filter only catches rows that **expose the constrained DocType
as a Link column in their result**. If your report aggregates and
strips the link column, the global filter cannot trim that dimension.
For huge result sets, prefer pre-filtering at SQL using
`build_permission_where_sql` — the global filter is a safety net, not
a replacement.

The global filter does NOT touch `report_summary`, `chart`, or
`message`. Aggregated counts/totals baked into those keys may still
expose figures beyond the user's scope. Authors who care about that
should pre-filter at SQL.

### Bypass switch (for diagnosis)

If a missing-row complaint might be the global filter hiding the row,
you have two ways to disable post-filtering temporarily:

1. **Per-session** — set the Frappe flag in a Server Script:
   ```python
   frappe.flags.skip_global_user_permission_filter = True
   ```
2. **Site-wide** — set the System Setting
   `avientek_skip_global_user_permission_filter` to 1 (will need a
   matching Custom Field on `Avientek Settings`).

Re-enable by clearing the flag / setting.

### Adding a new DocType to the global filter

Edit `DEFAULT_FILTERED_DOCTYPES` in
`avientek/api/report_permission_filter.py`. No restart needed — Frappe
re-imports on next request. The user must have `User Permission` rows
on the new DocType for it to take effect.

### When NOT to rely on the global filter

* The report must be performant on UNFILTERED data, since post-filter
  runs after the SQL. For million-row queries, pre-filter at SQL.
* If the constrained DocType is computed in Python (not a real Link
  column), the global filter can't see it — you must call
  `filter_rows_by_user_permissions` yourself before returning.
