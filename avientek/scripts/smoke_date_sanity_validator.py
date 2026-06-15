"""Smoke for the 2026-06-15 validate_date_sanity hook.

Sridhar/Jithin 2026-06-12 + 2026-06-15: SO-LTD-25-00302 was saved
with `transaction_date = '0205-03-31'` (year 205 CE instead of 2025).
Standard ERPNext + Frappe accept any Python-valid date (year 1-9999)
so a dropped-digit typo slipped through every layer.

Hook (avientek.events.utils.validate_date_sanity) rejects any year
outside [1900, 2100] on common parent-level date fields. Wired on
`before_save` for Quotation / Sales Order / Sales Invoice / Purchase
Order / Purchase Receipt / Purchase Invoice / Delivery Note /
Payment Entry / Journal Entry.

The smoke covers:

  Structural (3):
    A. validate_date_sanity exists in avientek.events.utils
    B. _DATE_SANITY_MIN_YEAR / _DATE_SANITY_MAX_YEAR are 1900 / 2100
    C. hooks.py wires the validator on all 9 target doctypes'
       before_save

  Behavioural (10):
    1. Year 205 (dropped-digit typo) → THROWS
    2. Year 9999 (max-out typo) → THROWS
    3. Year 2025 (today) → PASSES
    4. Year 1900 (boundary low) → PASSES
    5. Year 2100 (boundary high) → PASSES
    6. Year 1899 (one below low) → THROWS
    7. Year 2101 (one above high) → THROWS
    8. None / "" / missing field → PASSES (no false-positive)
    9. Multiple bad fields → ONE error mentioning ALL of them
   10. Unparseable garbage in date field → silent pass (Frappe's own
       parse error fires first)

Usage:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_date_sanity_validator.run
"""

import frappe


_TARGET_DOCTYPES = (
    "Quotation", "Sales Order", "Sales Invoice",
    "Purchase Order", "Purchase Receipt", "Purchase Invoice",
    "Delivery Note", "Payment Entry", "Journal Entry",
)


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


# ---------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------


def _check_function_exists():
    print()
    print("=== A. validate_date_sanity exists in avientek.events.utils ===")
    from avientek.events import utils
    if not hasattr(utils, "validate_date_sanity"):
        _fail("avientek.events.utils.validate_date_sanity missing")
    if not callable(utils.validate_date_sanity):
        _fail("validate_date_sanity is not callable")
    _ok("avientek.events.utils.validate_date_sanity defined")


def _check_year_bounds():
    print()
    print("=== B. Year bounds = [1900, 2100] ===")
    from avientek.events import utils
    if utils._DATE_SANITY_MIN_YEAR != 1900:
        _fail(f"_DATE_SANITY_MIN_YEAR = {utils._DATE_SANITY_MIN_YEAR}, expected 1900")
    if utils._DATE_SANITY_MAX_YEAR != 2100:
        _fail(f"_DATE_SANITY_MAX_YEAR = {utils._DATE_SANITY_MAX_YEAR}, expected 2100")
    _ok("[1900, 2100] (covers every plausible Avientek business doc)")


def _check_hooks_wired():
    print()
    print("=== C. hooks.py wires validate_date_sanity on all 9 target doctypes ===")
    import os
    path = frappe.get_app_path("avientek", "hooks.py")
    with open(path) as f:
        src = f.read()
    import re
    needle = "avientek.events.utils.validate_date_sanity"
    missing = []
    for dt in _TARGET_DOCTYPES:
        # Find the doctype block ("Sales Order": { ... }) — match the
        # block's name + the next closing '},' on its own indent.
        m = re.search(
            rf'"{re.escape(dt)}":\s*\{{(.*?)\n    \}}',
            src, re.S,
        )
        if not m:
            _fail(f"hooks.py missing doc_events block for {dt!r}")
        block = m.group(1)
        if needle not in block:
            missing.append(dt)
    if missing:
        _fail(f"validate_date_sanity NOT wired on: {missing}")
    _ok(f"all 9 doctypes: {', '.join(_TARGET_DOCTYPES)}")


# ---------------------------------------------------------------------
# Behavioural — minimal stub doc that the hook can read
# ---------------------------------------------------------------------


class _StubDoc:
    """The hook only calls doc.get(fieldname). A dict-like stub is enough."""

    def __init__(self, **kw):
        self._fields = dict(kw)

    def get(self, key, default=None):
        return self._fields.get(key, default)


def _run(**fields):
    """Run the validator with the given fields. Returns (True, None) if
    no throw; (False, msg) if frappe.throw fired.
    """
    from avientek.events.utils import validate_date_sanity
    doc = _StubDoc(**fields)
    try:
        validate_date_sanity(doc, "before_save")
    except frappe.ValidationError as e:
        return False, str(e)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    return True, None


def _check_behavioural():
    print()
    print("=== Behavioural: 10 scenarios via stub docs ===")

    # 1. Year 205 (the actual reported typo)
    ok, err = _run(transaction_date="0205-03-31")
    if ok:
        _fail("Year 205 should be REJECTED but passed")
    if "0205-03-31" not in err and "year out of range" not in err.lower():
        _fail(f"Year 205 rejected but error message off: {err!r}")
    _ok("Case 1 — Year 205 (dropped-digit typo): REJECTED")

    # 2. Year 9999
    ok, err = _run(transaction_date="9999-12-31")
    if ok:
        _fail("Year 9999 should be REJECTED but passed")
    _ok("Case 2 — Year 9999 (max-out typo): REJECTED")

    # 3. Year 2025 (today)
    ok, err = _run(transaction_date="2025-06-15")
    if not ok:
        _fail(f"Year 2025 should PASS but blocked: {err}")
    _ok("Case 3 — Year 2025 (today): PASSES")

    # 4. Year 1900 (boundary low — inclusive)
    ok, err = _run(transaction_date="1900-01-01")
    if not ok:
        _fail(f"Year 1900 (boundary) should PASS but blocked: {err}")
    _ok("Case 4 — Year 1900 (boundary low): PASSES (inclusive)")

    # 5. Year 2100 (boundary high — inclusive)
    ok, err = _run(transaction_date="2100-12-31")
    if not ok:
        _fail(f"Year 2100 (boundary) should PASS but blocked: {err}")
    _ok("Case 5 — Year 2100 (boundary high): PASSES (inclusive)")

    # 6. Year 1899 (one below)
    ok, err = _run(transaction_date="1899-12-31")
    if ok:
        _fail("Year 1899 should be REJECTED but passed")
    _ok("Case 6 — Year 1899 (one below bound): REJECTED")

    # 7. Year 2101 (one above)
    ok, err = _run(transaction_date="2101-01-01")
    if ok:
        _fail("Year 2101 should be REJECTED but passed")
    _ok("Case 7 — Year 2101 (one above bound): REJECTED")

    # 8. None / empty / missing → no false positive
    for label, fields in [
        ("None date", {"transaction_date": None}),
        ("Empty string", {"transaction_date": ""}),
        ("Field missing", {}),
    ]:
        ok, err = _run(**fields)
        if not ok:
            _fail(f"Case 8 {label!r}: should PASS but blocked: {err}")
    _ok("Case 8 — None / empty / missing date field: PASSES (no false-positive)")

    # 9. Multiple bad fields → SINGLE error mentioning all of them
    ok, err = _run(
        transaction_date="0205-03-31",
        delivery_date="0205-03-31",
        posting_date="0099-12-31",
    )
    if ok:
        _fail("Three bad fields should be REJECTED")
    # Count how many of the 3 fieldnames appear in the error
    mentions = sum(int(f in (err or "")) for f in (
        "transaction_date", "delivery_date", "posting_date",
    ))
    # Frappe's `unscrub` converts to title case so check for both styles
    title_mentions = sum(int(t in (err or "")) for t in (
        "Transaction Date", "Delivery Date", "Posting Date",
    ))
    total = max(mentions, title_mentions)
    if total < 3:
        _fail(
            f"Multi-field error should mention all 3 fields; "
            f"found {total}. err={err!r}"
        )
    _ok("Case 9 — Multiple bad fields: SINGLE error lists all 3")

    # 10. Unparseable garbage → silent pass (let Frappe's own parser throw)
    ok, err = _run(transaction_date="not-a-date")
    if not ok:
        _fail(f"Unparseable date should silently pass — Frappe's own parser will catch it. Got: {err}")
    _ok("Case 10 — Unparseable garbage: silent pass (Frappe parser handles)")


def run():
    print("=" * 64)
    print("Avientek smoke: validate_date_sanity (dropped-digit year typo guard)")
    print("=" * 64)
    _check_function_exists()
    _check_year_bounds()
    _check_hooks_wired()
    _check_behavioural()
    print()
    print("All smoke checks PASSED ✓")
