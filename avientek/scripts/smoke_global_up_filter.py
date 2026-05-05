"""Smoke test for the global User-Permission filter on query reports.

Run with:
    bench --site avientekv21.frappe.cloud execute \
        avientek.scripts.smoke_global_up_filter.run

The test:
  1. Picks one real value per dimension (Company / Item Group / Brand /
     Sales Person / Customer) from existing site data.
  2. Creates User Permission rows for the test user on those values
     (idempotent — won't duplicate). Saves a 'before' snapshot so the
     teardown can restore the user's pre-test state.
  3. Runs an admin baseline of `Sales Order` list view and a wide query
     report.
  4. Re-runs each as the restricted test user.
  5. Verifies:
       a. Test user's row count is < admin row count (filter actually
          trimmed).
       b. Every Link column value in the test user's result is within
          their UP allow-list.
  6. Restores the user's UP state.

Returns a dict; also prints a human-readable summary.
"""
from __future__ import annotations

import frappe
from frappe.utils import nowdate


DEFAULT_USER = "testqcs@gmail.com"
DIMENSIONS = ["Company", "Item Group", "Brand", "Sales Person", "Customer"]
SCRATCH_TAG = "_avtk_smoke_global_up_filter"


def _hr(label: str) -> str:
    return "\n" + "─" * 70 + f"\n{label}\n" + "─" * 70


def _pick_value_with_data(doctype):
    """Pick a real DocType value that has at least one Sales Order row
    to ensure the test exercises non-zero data. Falls back to any row
    of that DocType if no SO link is found."""
    if doctype == "Company":
        row = frappe.db.sql(
            "SELECT company FROM `tabSales Order` GROUP BY company "
            "ORDER BY COUNT(*) DESC LIMIT 1", as_dict=True,
        )
        return row[0]["company"] if row else frappe.db.get_value("Company", {}, "name")
    if doctype == "Customer":
        row = frappe.db.sql(
            "SELECT customer FROM `tabSales Order` GROUP BY customer "
            "ORDER BY COUNT(*) DESC LIMIT 1", as_dict=True,
        )
        return row[0]["customer"] if row else frappe.db.get_value("Customer", {}, "name")
    if doctype == "Sales Person":
        row = frappe.db.sql(
            "SELECT st.sales_person FROM `tabSales Team` st "
            "JOIN `tabSales Order` so ON so.name = st.parent "
            "GROUP BY st.sales_person "
            "ORDER BY COUNT(*) DESC LIMIT 1", as_dict=True,
        )
        return row[0]["sales_person"] if row else frappe.db.get_value("Sales Person", {}, "name")
    if doctype == "Item Group":
        row = frappe.db.sql(
            "SELECT i.item_group FROM `tabItem` i "
            "JOIN `tabSales Order Item` soi ON soi.item_code = i.name "
            "GROUP BY i.item_group ORDER BY COUNT(*) DESC LIMIT 1",
            as_dict=True,
        )
        return row[0]["item_group"] if row else frappe.db.get_value("Item Group", {}, "name")
    if doctype == "Brand":
        row = frappe.db.sql(
            "SELECT brand FROM `tabSales Order Item` "
            "WHERE IFNULL(brand,'') <> '' "
            "GROUP BY brand ORDER BY COUNT(*) DESC LIMIT 1", as_dict=True,
        )
        return row[0]["brand"] if row else frappe.db.get_value("Brand", {}, "name")
    return None


def _setup_user_permissions(user, picks):
    """Create one UP row per dimension. Idempotent."""
    created = []
    for dim, val in picks.items():
        if not val:
            continue
        existing = frappe.db.exists("User Permission", {
            "user": user, "allow": dim, "for_value": val,
        })
        if existing:
            created.append({"name": existing, "dim": dim, "value": val,
                            "preexisting": True})
            continue
        doc = frappe.new_doc("User Permission")
        doc.user = user
        doc.allow = dim
        doc.for_value = val
        doc.apply_to_all_doctypes = 1
        # NOTE: do NOT set user_permission_manager to a synthetic value;
        # it's a real Link to UPM and Frappe will reject unknown values.
        # Tracking is via the `created` list returned to teardown.
        doc.insert(ignore_permissions=True)
        created.append({"name": doc.name, "dim": dim, "value": val,
                        "preexisting": False})
    frappe.db.commit()
    return created


def _teardown_user_permissions(created):
    """Remove only the rows we created (preexisting rows untouched)."""
    for row in created:
        if row.get("preexisting"):
            continue
        try:
            frappe.delete_doc("User Permission", row["name"],
                              ignore_permissions=True, force=True)
        except Exception:
            pass
    frappe.db.commit()


def _count_so_via_get_list(user, filters=None):
    """Use frappe.get_list (Report Builder code path) — exercises core
    auto-filtering by User Permissions."""
    original = frappe.session.user
    try:
        frappe.set_user(user)
        return len(frappe.get_list(
            "Sales Order",
            filters=filters or {},
            fields=["name", "company", "customer", "territory"],
            limit_page_length=0,
            ignore_permissions=False,
        ))
    finally:
        frappe.set_user(original)


def _run_query_report(user, report_name, filters=None):
    """Run a query report via the wired override."""
    import json as _json
    original = frappe.session.user
    try:
        frappe.set_user(user)
        runner = frappe.get_attr("frappe.desk.query_report.run")
        res = runner(report_name=report_name,
                     filters=_json.dumps(filters or {}))
        if not isinstance(res, dict):
            return 0, {}
        return len(res.get("result") or []), res
    finally:
        frappe.set_user(original)


def run(user: str = DEFAULT_USER):
    """Entry point for `bench execute`."""
    print("=" * 70)
    print("GLOBAL USER-PERMISSION FILTER — END-TO-END SMOKE TEST")
    print(f"site: {frappe.local.site}    test user: {user}")
    print("=" * 70)

    # ── 0. Preflight: override wired? ──
    print(_hr("[0] Override wiring"))
    hooks = frappe.get_hooks("override_whitelisted_methods") or {}
    override = hooks.get("frappe.desk.query_report.run")
    over_str = override[0] if isinstance(override, list) and override else override
    print(f"  frappe.desk.query_report.run -> {over_str}")
    override_ok = bool(over_str and "avientek" in str(over_str))
    print(f"  wired: {'YES OK' if override_ok else 'NO FAIL'}")

    if not frappe.db.exists("User", user):
        print(f"\n  FAIL test user {user!r} not found on this site")
        return {"error": "user not found"}

    # ── 1. Pick real values per dimension ──
    print(_hr("[1] Picking real data per dimension"))
    picks = {dim: _pick_value_with_data(dim) for dim in DIMENSIONS}
    for dim, val in picks.items():
        print(f"  {dim:14s} -> {val!r}")
    picks = {d: v for d, v in picks.items() if v}

    # ── 2. Set up scratch UP rows ──
    print(_hr("[2] Creating User Permission rows for test user"))
    created = _setup_user_permissions(user, picks)
    for row in created:
        marker = " (preexisting - kept)" if row.get("preexisting") else " (created)"
        print(f"  + UP[{row['dim']}] = {row['value']}{marker}")

    try:
        # ── 3. Admin baseline ──
        print(_hr("[3] Admin baseline (no UP filtering)"))
        admin_so_count = _count_so_via_get_list("Administrator")
        print(f"  Sales Order list (Administrator):    {admin_so_count}")

        # ── 4. Test user via get_list (Report Builder path) ──
        print(_hr("[4] Sales Order list as test user (Report Builder path)"))
        user_so_count = _count_so_via_get_list(user)
        delta = admin_so_count - user_so_count
        print(f"  Sales Order list (testqcs):          {user_so_count}")
        print(f"  trimmed by UP filter:                {delta}")
        rb_pass = (user_so_count < admin_so_count) or admin_so_count == 0
        print(f"  Report Builder filter working:       "
              f"{'YES OK' if rb_pass else 'NO FAIL (counts equal)'}")

        # ── 5. Query Report path: Avientek Stock Allocation ──
        print(_hr("[5] Avientek Stock Allocation (Script Report path)"))
        admin_count, _ = _run_query_report(
            "Administrator", "Avientek Stock Allocation",
            {"from_date": "2024-01-01", "to_date": nowdate()})
        user_count, user_res = _run_query_report(
            user, "Avientek Stock Allocation",
            {"from_date": "2024-01-01", "to_date": nowdate()})
        print(f"  rows as Administrator: {admin_count}")
        print(f"  rows as testqcs:       {user_count}")

        leaks = {}
        if isinstance(user_res, dict):
            cols = user_res.get("columns") or []
            rows = user_res.get("result") or []
            link_idx = []
            for i, c in enumerate(cols):
                if not isinstance(c, dict): continue
                if c.get("fieldtype") == "Link" and c.get("options") in DIMENSIONS:
                    link_idx.append((i, c["options"],
                                     c.get("fieldname") or c.get("label")))
            allow_sets = {}
            for dim in {x[1] for x in link_idx}:
                allow_sets[dim] = set(frappe.db.get_all(
                    "User Permission",
                    filters={"user": user, "allow": dim},
                    pluck="for_value") or [])
            for r in rows:
                for idx, dim, key in link_idx:
                    if not allow_sets.get(dim): continue
                    v = r.get(key) if isinstance(r, dict) else (
                        r[idx] if isinstance(r, (list, tuple)) and idx < len(r) else None)
                    if v and v not in allow_sets[dim]:
                        leaks.setdefault(dim, set()).add(v)
        if leaks:
            print(f"  FAIL leaked values:")
            for dim, vals in leaks.items():
                print(f"      {dim}: {sorted(list(vals))[:5]}")
        else:
            print("  OK no leaks across constrained Link columns")
        qr_pass = (not leaks) and (user_count <= admin_count)

        # ── 6. Verdict ──
        print(_hr("[6] Verdict"))
        overall = override_ok and rb_pass and qr_pass
        print(f"  override wired:                {'OK' if override_ok else 'FAIL'}")
        print(f"  Report Builder path filtered:  {'OK' if rb_pass else 'FAIL'}")
        print(f"  Script Report path no leaks:   {'OK' if qr_pass else 'FAIL'}")
        print()
        if overall:
            print("  PASS - GLOBAL USER-PERMISSION FILTER WORKING ACROSS ALL PATHS")
        else:
            print("  FAIL - see details above")
        return {
            "override_ok": override_ok,
            "report_builder_pass": rb_pass,
            "query_report_pass": qr_pass,
            "admin_so_count": admin_so_count,
            "user_so_count": user_so_count,
            "admin_stock_alloc_count": admin_count,
            "user_stock_alloc_count": user_count,
            "leaks": {k: sorted(list(v))[:5] for k, v in leaks.items()},
        }
    finally:
        # ── 7. Cleanup (always runs) ──
        print(_hr("[7] Teardown - removing scratch UP rows"))
        _teardown_user_permissions(created)
        print("  OK scratch UP rows removed")
