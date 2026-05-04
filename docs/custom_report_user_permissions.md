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
