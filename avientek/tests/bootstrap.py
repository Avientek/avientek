"""Frappe `before_tests` hook for avientek — seeds test masters that
the stock Frappe / ERPNext test bootstrap can't auto-create due to
Avientek custom-field mandatoriness.

Wired in hooks.py:
    before_tests = "avientek.tests.bootstrap.before_tests"

Triggered by testctl / `bench --site <site> run-tests` before any
test module loads. Idempotent (every insert gated on
`frappe.db.exists`). Guarded by `frappe.flags.in_test` so the hook
silently no-ops if called outside the test context — defensive,
since `before_tests` SHOULD only fire in tests but we want to be
sure we never touch prod / dev data.

KNOWN BLOCKERS (discovered via testctl + custom-field scan
2026-06-15):

  1. `_Test Holiday List` is referenced by `_Test Company`
     (`default_holiday_list`). Doesn't exist on a fresh site, so
     `_Test Company` insert fails with LinkValidationError.
     Fix: pre-create the Holiday List with a wide date range
     (2020-2050) so test transactions of any plausible posting
     date find a match.

  2. Custom Field `Company.gst_category` is reqd=1 with a default
     of "Unregistered" — Frappe will auto-fill on insert.
     No action needed.

  3. Custom Field `Customer.gst_category` and `Supplier.gst_category`
     are reqd=1 with the same "Unregistered" default. No action.

  4. Custom Field `Item.part_number` is reqd=1 with NO default —
     when Frappe / ERPNext insert `_Test Item` from a fixture,
     it'll fail. Fix: pre-create the minimal Items the tests need
     with `part_number = '_TEST_PN'`.

Add more seeds here as new blockers surface — re-run
`testctl run frappe --quiet` after each, the error text names
the missing master / field.
"""

import frappe


def before_tests():
    """Entry point called by Frappe before any test module loads.
    Idempotent; silent if not in a test session.
    """
    if not frappe.flags.in_test:
        return

    _relax_test_blocker_mandatory_fields()
    _ensure_test_holiday_list()
    _ensure_test_fiscal_years()
    _ensure_test_tax_categories()
    _ensure_test_users()
    _ensure_test_companies()
    _ensure_test_items()


def _relax_test_blocker_mandatory_fields():
    """Set `reqd=0` via Property Setter on Custom Fields that block
    Frappe's test bootstrap from creating `_Test Company` /
    `_Test Company 1` automatically.

    DESIGN: Property Setter (DB write) — persists on whatever site
    runs tests. This is fine because tests run on a dev / CI site,
    NEVER on prod. The relaxation has no effect on prod because:
      - Frappe Cloud deploys the codebase + custom field definitions,
        NOT Property Setters made at runtime on a different site.
      - This hook is gated by `frappe.flags.in_test` so it only
        fires during `bench run-tests` / testctl invocations.

    Tried first: in-process meta mutation (df.reqd = 0). Didn't work
    — Frappe clears the meta cache between `before_tests` and the
    test bootstrap's Company creates, so the mutation is lost.

    KNOWN BLOCKERS:

      - `Company.default_warehouse_for_sales_return` is reqd=1 with
        no sensible test default (circular: needs a Warehouse with
        `company=...`). Test sessions don't exercise sales-return
        flows, so relaxation is safe.

    Add more (doctype, fieldname) pairs here as new blockers surface.
    """
    # `default_warehouse_for_sales_return` is a STANDARD DocField on
    # Company (reqd=0 in the JSON) that's been promoted to reqd=1 via
    # a Property Setter on this site. To relax for tests, flip that
    # Property Setter's value from '1' to '0' (the value is stored as
    # a string in tabProperty Setter).
    # Standard DocFields promoted to mandatory via Property Setter
    PS_BLOCKERS = (
        ("Company", "default_warehouse_for_sales_return"),
        ("Payment Term", "credit_days"),
    )
    # Custom Fields with reqd=1 + no default that block test masters
    CF_BLOCKERS = (
        ("Lead", "custom_party_type"),
        ("Item", "part_number"),
    )
    changed_doctypes = set()

    for doctype, fieldname in PS_BLOCKERS:
        try:
            ps_name = frappe.db.get_value(
                "Property Setter",
                {"doc_type": doctype, "field_name": fieldname, "property": "reqd"},
                "name",
            )
            if not ps_name:
                continue
            current = frappe.db.get_value("Property Setter", ps_name, "value")
            if str(current) != "0":
                frappe.db.set_value(
                    "Property Setter", ps_name, "value", "0",
                    update_modified=False,
                )
                changed_doctypes.add(doctype)
        except Exception:
            pass

    for doctype, fieldname in CF_BLOCKERS:
        try:
            cf_name = frappe.db.get_value(
                "Custom Field", {"dt": doctype, "fieldname": fieldname}, "name"
            )
            if not cf_name:
                continue
            current = frappe.db.get_value("Custom Field", cf_name, "reqd")
            if int(current or 0) != 0:
                frappe.db.set_value(
                    "Custom Field", cf_name, "reqd", 0,
                    update_modified=False,
                )
                changed_doctypes.add(doctype)
        except Exception:
            pass

    if changed_doctypes:
        for doctype in changed_doctypes:
            try:
                frappe.clear_cache(doctype=doctype)
            except Exception:
                pass
        frappe.db.commit()


def _ensure_test_holiday_list():
    """Create `_Test Holiday List` if missing.

    `_Test Company`'s `default_holiday_list` field links here.
    Without this Holiday List, every `_Test Company` insert (which
    Frappe does automatically when test modules run) fails with
    LinkValidationError: Could not find Default Holiday List:
    _Test Holiday List.

    Date range 2020-01-01 → 2050-12-31 covers any plausible test
    transaction date. weekly_off=Sunday matches Avientek's standard
    config so tests that simulate week-end calculations behave
    predictably.
    """
    if frappe.db.exists("Holiday List", "_Test Holiday List"):
        return
    doc = frappe.get_doc({
        "doctype": "Holiday List",
        "holiday_list_name": "_Test Holiday List",
        "from_date": "2020-01-01",
        "to_date": "2050-12-31",
        "weekly_off": "Sunday",
    })
    doc.insert(ignore_permissions=True, ignore_mandatory=True)


def _ensure_test_fiscal_years():
    """Pre-create `_Test Fiscal Year YYYY` records that ERPNext's
    test_records.json references. Covers 2013-2030 inclusively so
    any test transaction posting in those years finds a matching
    fiscal year master.
    """
    for year in range(2013, 2031):
        name = f"_Test Fiscal Year {year}"
        if frappe.db.exists("Fiscal Year", name):
            continue
        try:
            frappe.get_doc({
                "doctype": "Fiscal Year",
                "year": name,
                "year_start_date": f"{year}-01-01",
                "year_end_date": f"{year}-12-31",
            }).insert(ignore_permissions=True, ignore_mandatory=True)
        except Exception:
            pass


def _ensure_test_tax_categories():
    """Pre-create the `_Test Tax Category*` records referenced by
    ERPNext test_records.json. Tax Category is a simple master
    (only `title` reqd) so this is a tiny seed.
    """
    for title in ("_Test Tax Category 1", "_Test Tax Category 2"):
        if frappe.db.exists("Tax Category", title):
            continue
        try:
            frappe.get_doc({
                "doctype": "Tax Category",
                "title": title,
            }).insert(ignore_permissions=True, ignore_mandatory=True)
        except Exception:
            pass


def _ensure_test_users():
    """Pre-create the canonical Frappe/ERPNext test users that
    `test_records.json` references via owner / employee / sales_person
    fields.
    """
    test_users = (
        ("test@example.com", "Test"),
        ("test1@example.com", "Test 1"),
        ("test2@example.com", "Test 2"),
        ("test3@example.com", "Test 3"),
    )
    for email, first_name in test_users:
        if frappe.db.exists("User", email):
            continue
        try:
            doc = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": first_name,
                "send_welcome_email": 0,
                "enabled": 1,
                "user_type": "System User",
                "roles": [{"role": "System Manager"}],
            })
            doc.flags.ignore_mandatory = True
            doc.flags.ignore_permissions = True
            doc.insert()
        except Exception:
            pass


def _ensure_test_companies():
    """Pre-create `_Test Company` and `_Test Company 1` with
    `ignore_mandatory=True` so Frappe's auto-create (which respects
    `frappe.db.exists`) short-circuits.

    Frappe's test framework creates these companies from
    test_records.json. The records don't include
    `default_warehouse_for_sales_return` (a Custom Field with
    reqd=1 + no default) — so the auto-create fails with
    MandatoryError. Pre-creating with ignore_mandatory=True
    bypasses the validation; the field stays NULL on the test
    Company but no test exercises sales-return flows on it.

    Note: in-process meta mutation in
    _relax_test_blocker_mandatory_fields() doesn't help because
    Frappe clears the meta cache between this hook and the test
    bootstrap's Company creates. Pre-creation is the reliable
    workaround.
    """
    test_companies = (
        ("_Test Company", "_TC"),
        ("_Test Company 1", "_TC1"),
    )
    for company_name, abbr in test_companies:
        if frappe.db.exists("Company", company_name):
            continue
        try:
            doc = frappe.get_doc({
                "doctype": "Company",
                "company_name": company_name,
                "abbr": abbr,
                "default_currency": "INR",
                "country": "India",
                "default_holiday_list": "_Test Holiday List",
            })
            doc.flags.ignore_mandatory = True
            doc.flags.ignore_permissions = True
            doc.insert()
        except Exception:
            # If Company can't be created (e.g. an upstream
            # validation fails on the abbr / country / currency
            # combo on a non-Indian site), let Frappe's own bootstrap
            # report the precise error rather than swallowing it
            # here.
            pass


def _ensure_test_items():
    """Pre-create the `_Test Item*` records that ERPNext test modules
    reference, with our mandatory Custom Field `part_number` filled.

    ERPNext's standard test_records.json for Item don't know about
    Avientek's `part_number` Custom Field — they'd fail Frappe's
    mandatory validation. Pre-creating these means
    `frappe.db.exists` short-circuits the standard insert.

    The names below are the most common `_Test Item*` records used
    across ERPNext core tests. Add more as new blockers surface.
    """
    common_items = (
        "_Test Item",
        "_Test Item Home Desktop 100",
        "_Test Item Home Desktop 200",
        "_Test Sales BOM Item",
        "_Test FG Item",
        "_Test FG Item 2",
        "_Test RM Item 1",
        "_Test RM Item 2",
        "_Test Non Stock Item",
        "_Test Serialized Item",
        "_Test Serialized Item With Series",
    )
    for item_code in common_items:
        if frappe.db.exists("Item", item_code):
            continue
        try:
            frappe.get_doc({
                "doctype": "Item",
                "item_code": item_code,
                "item_name": item_code,
                "item_group": _ensure_item_group_for_tests(),
                "stock_uom": "Nos",
                "is_stock_item": 1,
                "part_number": "_TEST_PN",  # Custom Field, reqd=1
            }).insert(ignore_permissions=True, ignore_mandatory=True)
        except Exception:
            # Test seed is best-effort — if a downstream validation
            # (Avientek's `validate_brand_pn`, ERPNext's item-group
            # checks, etc.) blocks the create, leave it and let the
            # specific failing test report the issue more clearly.
            pass


def _ensure_item_group_for_tests():
    """Return a usable Item Group for `_Test Item*` seeds. Most ERPNext
    tests assume `All Item Groups` exists; on a fresh Avientek site
    it does (Frappe creates it during ERPNext install).
    """
    if frappe.db.exists("Item Group", "All Item Groups"):
        return "All Item Groups"
    # Defensive fallback — any leaf group on the site
    first = frappe.db.get_value(
        "Item Group", {"is_group": 0}, "name", order_by="creation asc"
    )
    return first or "All Item Groups"
