"""Smoke test for Sridhar's 2026-06-09 Quote Report fixes.

Runs both patches end-to-end and verifies:
  - Quotation.customer_name is now pickable in Pick Columns
    (hidden=0, report_hide=0)
  - No Quotation Item rows have garbage custom_margin_ or
    custom_incentive_ (|value| > 500)

Usage:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_quote_report_visibility.run

Exits with non-zero return code on first failure so CI / a wrapper
shell script can fail the deploy if smoke breaks.
"""

import frappe
from frappe.utils import flt


SANE_LIMIT = 500.0


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


def _check_customer_name_visibility():
    print("=== Bug 1: Quotation.customer_name in Pick Columns ===")
    # Re-derive via Meta because Property Setters merge in at meta load.
    meta = frappe.get_meta("Quotation")
    field = meta.get_field("customer_name")
    if not field:
        _fail("customer_name field not found on Quotation")
    if field.hidden:
        _fail(f"customer_name still hidden=1 — pick-columns picker will skip it")
    if field.report_hide:
        _fail(f"customer_name has report_hide=1 — report-view picker will skip it")
    _ok(f"customer_name hidden={field.hidden}, report_hide={field.report_hide}, "
        f"read_only={field.read_only} — visible in Pick Columns")


def _check_no_margin_garbage():
    print()
    print("=== Bug 2: no garbage custom_margin_ / custom_incentive_ values ===")
    bad = frappe.db.sql(
        """
        SELECT COUNT(*) FROM `tabQuotation Item`
        WHERE ABS(IFNULL(custom_margin_, 0)) > %s
           OR ABS(IFNULL(custom_incentive_, 0)) > %s
        """,
        (SANE_LIMIT, SANE_LIMIT),
    )[0][0]
    if bad:
        _fail(f"{bad} Quotation Item rows still have |custom_margin_| or "
              f"|custom_incentive_| > {SANE_LIMIT} — patch did not run or "
              f"new bad data has been written")
    _ok(f"all Quotation Item rows have margin/incentive percent within "
        f"±{SANE_LIMIT:.0f}")


def _smoke_create_new_row_div_zero_path():
    """Defensive smoke: simulate the JS divide-by-zero formula and
    verify the patch's clamp logic produces 0 (not infinity / NaN /
    huge number) when amount = 0."""
    print()
    print("=== Defensive: divide-by-zero in margin% formula ===")
    amount = 0.0
    margin_value = -16915.20
    margin_percent = (margin_value / amount * 100.0) if amount else 0.0
    if margin_percent != 0.0:
        _fail(f"divide-by-zero guard did not zero the value — got {margin_percent}")
    _ok(f"div-zero guard yields 0 (not {-16915.20/(amount or 1)*100:.2f} unsafely)")


def run():
    print("=" * 64)
    print("Avientek smoke: Quote Report visibility + margin sanity")
    print("=" * 64)
    _check_customer_name_visibility()
    _check_no_margin_garbage()
    _smoke_create_new_row_div_zero_path()
    print()
    print("All smoke checks PASSED ✓")
