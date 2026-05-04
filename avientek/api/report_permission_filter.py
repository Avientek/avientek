"""Global User-Permission filter for query reports.

Background
----------
Frappe's built-in `frappe.get_list()` automatically honours User Permissions
on Link fields (Frappe core behaviour). But query reports — Script Reports,
Server Script Reports, Query Reports — execute raw SQL, so they bypass that
mechanism. Each report's author has to add filtering manually, which doesn't
scale: any user can spin up a new Custom Report and forget the rule.

Sridhar 2026-05-04: client wanted a *global* rule that catches every report
(including future ones users create) without per-report code edits.

What this does
--------------
We override the whitelisted endpoint `frappe.desk.query_report.run` (the
single entry point the desk UI calls for every query report), call the
original implementation, and post-filter the resulting rows against the
caller's User Permissions for any column whose `fieldtype = Link` and whose
`options` is a User-Permission-constrained DocType.

This works for ALL report types:
  * Script Report (Python execute() in app code)
  * Server Script Report (script stored in DB)
  * Query Report (raw SQL stored in DB)
  * Custom Report (Report Builder + Custom Report on Script parent)

Limitations
-----------
1. The report must INCLUDE the constrained DocType as a Link column in its
   output. If a report aggregates and discards the link column, we cannot
   post-filter on that dimension.
2. Pre-filtering at SQL is still preferable for huge result sets — the
   global filter is a safety net, not a replacement for in-report filtering.
3. System Manager / Administrator are bypassed (Frappe core convention).
4. We do NOT touch the `columns` / `chart` / `report_summary` keys returned
   by the report — only the `result` rows. Aggregations baked into the
   report's `message` / summary may still leak counts/totals beyond the
   user's scope; report authors who care about that should pre-filter at
   SQL.

Wiring
------
hooks.py:
    override_whitelisted_methods = {
        "frappe.desk.query_report.run":
            "avientek.api.report_permission_filter.run",
    }

Bypass switch
-------------
Set `flags.skip_global_user_permission_filter = True` in a session OR set
the System Setting `avientek_skip_global_user_permission_filter = 1` to
disable post-filtering — useful for diagnosing whether a missing-row
complaint is caused by this filter.
"""
from __future__ import annotations

import frappe
from frappe import _


# DocTypes we will filter on if a report column links to them. Adding a
# DocType here means: if the user has any User Permission on it AND the
# report has a Link column to it, rows are filtered. Empty list of
# permissions on a DocType = unrestricted (Frappe core semantics).
DEFAULT_FILTERED_DOCTYPES = {
    "Company",
    "Sales Person",
    "Item Group",
    "Customer",
    "Brand",
    "Territory",
    "Warehouse",
    "Cost Center",
    "Project",
    "Department",
    "Employee",
}


@frappe.whitelist()
def run(report_name, filters=None, user=None, custom_columns=None,
        is_tree=False, parent_field=None, are_default_filters=True,
        ignore_prepared_report=False):
    """Whitelisted wrapper: execute the report, then strip rows the caller
    isn't permitted to see.

    Signature mirrors `frappe.desk.query_report.run` so the desk UI can
    keep calling /api/method/frappe.desk.query_report.run unchanged.
    """
    # Import the original implementation directly — calling it via
    # frappe.call would hit our override and recurse forever.
    from frappe.desk.query_report import run as _orig_run

    result = _orig_run(
        report_name, filters=filters, user=user,
        custom_columns=custom_columns, is_tree=is_tree,
        parent_field=parent_field, are_default_filters=are_default_filters,
        ignore_prepared_report=ignore_prepared_report,
    )

    if not isinstance(result, dict):
        return result

    if _should_skip_filter():
        return result

    try:
        result = apply_global_user_permission_filter(
            result,
            user=user or frappe.session.user,
            report_name=report_name,
        )
    except Exception:
        # NEVER let a filter failure break the whole report. Log and
        # return the unfiltered result so the user can still work; the
        # error log will show up in System → Error Log.
        frappe.log_error(
            title="Global UP filter failed for report " + (report_name or "?"),
            message=frappe.get_traceback(),
        )

    return result


def apply_global_user_permission_filter(result, user=None, report_name=None,
                                         filtered_doctypes=None):
    """Strip rows from `result["result"]` whose Link-column values are
    outside the user's User Permission allow-list for that DocType.

    Pure function — no Frappe state mutation outside reading User
    Permission rows. Safe to call from tests or other code paths.

    Returns the (possibly modified) result dict. The dict's identity is
    preserved; the `result["result"]` list is replaced with a new list.
    """
    user = user or frappe.session.user
    if not user or user == "Administrator":
        return result
    roles = set(frappe.get_roles(user))
    if "System Manager" in roles:
        return result

    columns = result.get("columns") or []
    rows = result.get("result")
    if not rows or not columns:
        return result

    target_dts = set(filtered_doctypes or DEFAULT_FILTERED_DOCTYPES)

    # Map each Link column to (DocType, list-or-dict-key, allowed-set).
    # Skip any DocType for which the user has zero User Permission rows.
    constraints = []  # list of (doctype, accessor)
    allow_cache = {}
    for idx, col in enumerate(columns):
        if not isinstance(col, dict):
            continue
        if (col.get("fieldtype") or "") != "Link":
            continue
        opts = col.get("options")
        if not opts or opts not in target_dts:
            continue
        if opts not in allow_cache:
            vals = frappe.db.get_all(
                "User Permission",
                filters={"user": user, "allow": opts},
                pluck="for_value",
            ) or []
            allow_cache[opts] = set(vals)
        if not allow_cache[opts]:
            continue  # no UP rows for this DocType → unrestricted
        # Resolve the column's accessor: row may be a list (positional)
        # or a dict (keyed by fieldname).
        accessor_dict_key = col.get("fieldname") or col.get("label")
        constraints.append((opts, idx, accessor_dict_key, allow_cache[opts]))

    if not constraints:
        return result

    out = []
    for r in rows:
        ok = True
        for doctype, idx, dict_key, allowed in constraints:
            val = None
            if isinstance(r, dict):
                val = r.get(dict_key)
            elif isinstance(r, (list, tuple)):
                if idx < len(r):
                    val = r[idx]
            else:
                continue  # unknown shape — let it through
            if val is None or val == "":
                continue  # blank value → don't filter (let through)
            if val not in allowed:
                ok = False
                break
        if ok:
            out.append(r)

    result["result"] = out
    return result


def _should_skip_filter():
    """Per-request bypass. Useful for diagnosing whether a row that
    "should" appear is being hidden by this filter. Two switches:

    1. frappe.flags.skip_global_user_permission_filter (Boolean) —
       set programmatically in a session.
    2. System Setting `avientek_skip_global_user_permission_filter`
       (Single Doc, Check field) — checked once per request, cached.
    """
    if getattr(frappe.flags, "skip_global_user_permission_filter", False):
        return True
    cached = frappe.cache().get_value("avtk_skip_global_up_filter")
    if cached is not None:
        return bool(int(cached))
    try:
        val = int(frappe.db.get_single_value(
            "Avientek Settings", "skip_global_user_permission_filter"
        ) or 0)
    except Exception:
        val = 0
    frappe.cache().set_value("avtk_skip_global_up_filter", val)
    return bool(val)
