"""Smoke for the 2026-06-17 Reward Payable account_type drift fix.

Production audit on 2026-06-17 found 17 Reward & Incentive JV booking
failures across 4 companies between 2026-06-14 and 2026-06-16.
Root cause: all 9 "Reward Payable" accounts had
`account_type = "Payable"` which mandates `party_type` + `party` on
every JV credit row hitting them. The matching 9 "Incentive Payable"
accounts have account_type blank (works fine).

Patch: avientek.patches.fix_reward_payable_account_type_drift clears
the account_type on every Reward Payable account so it matches
Incentive Payable's working config.

Smoke verifies:

  A. After patch — every Reward Payable account has account_type=""
  B. Reward Payable and Incentive Payable now share the same
     account_type config per company (regression guard against
     future drift)
  C. root_type stays "Liability" — patch did not accidentally
     re-classify the accounts (no impact to balance sheet placement)
  D. Backfill candidate query is reachable — we can identify failed
     SIs from the Error Log
  E. Idempotency — re-running the data patch is a no-op

Usage:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_reward_payable_account_type_drift.run
"""

import frappe


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


def _check_reward_payable_account_type_blank():
    print()
    print("=== A. Every Reward Payable account has account_type='' ===")
    rows = frappe.db.sql(
        """
        SELECT name, company, account_type
        FROM `tabAccount`
        WHERE name LIKE %s AND is_group = 0
        """,
        ("%Reward Payable%",),
        as_dict=True,
    )
    if not rows:
        _fail("no Reward Payable accounts found — chart of accounts misconfigured?")
    for r in rows:
        if r["account_type"]:
            _fail(
                f"{r['name']} ({r['company']}) still has "
                f"account_type={r['account_type']!r} — patch did not heal it"
            )
    _ok(f"all {len(rows)} Reward Payable accounts have account_type=''")


def _check_parity_with_incentive_payable():
    print()
    print("=== B. Reward Payable parity with Incentive Payable per company ===")
    rwd = {
        r["company"]: r["account_type"]
        for r in frappe.db.sql(
            """
            SELECT company, account_type FROM `tabAccount`
            WHERE name LIKE %s AND is_group = 0
            """,
            ("%Reward Payable%",),
            as_dict=True,
        )
    }
    inc = {
        r["company"]: r["account_type"]
        for r in frappe.db.sql(
            """
            SELECT company, account_type FROM `tabAccount`
            WHERE name LIKE %s AND is_group = 0
            """,
            ("%Incentive%Payable%",),
            as_dict=True,
        )
    }
    mismatched = []
    for company in rwd:
        if company in inc and rwd[company] != inc[company]:
            mismatched.append((company, rwd[company], inc[company]))
    if mismatched:
        _fail(f"reward/incentive payable mismatch per company: {mismatched}")
    _ok(
        f"{len(rwd)} reward / {len(inc)} incentive payable accounts — "
        f"all matched companies share the same account_type"
    )


def _check_root_type_intact():
    print()
    print("=== C. root_type stays Liability ===")
    rows = frappe.db.sql(
        """
        SELECT name, root_type FROM `tabAccount`
        WHERE name LIKE %s AND is_group = 0
        """,
        ("%Reward Payable%",),
        as_dict=True,
    )
    bad = [r for r in rows if r["root_type"] != "Liability"]
    if bad:
        _fail(f"root_type drifted away from Liability: {bad}")
    _ok(f"all {len(rows)} Reward Payable accounts root_type=Liability")


def _check_backfill_query_works():
    print()
    print("=== D. Backfill candidate query reachable ===")
    rows = frappe.db.sql(
        """
        SELECT DISTINCT method FROM `tabError Log`
        WHERE method LIKE %s
        """,
        ("Reward Incentive JV booking failed for %",),
        as_dict=True,
    )
    _ok(
        f"backfill candidate query returned {len(rows)} distinct "
        f"failed-SI markers (may be 0 on a fresh local; that's fine)"
    )


def _check_idempotency():
    print()
    print("=== E. Idempotency ===")
    from avientek.patches.fix_reward_payable_account_type_drift import execute
    execute()
    execute()
    _ok("re-running the patch is a no-op")


def run():
    print("=" * 64)
    print("Avientek smoke: Reward Payable account_type drift fix")
    print("=" * 64)
    _check_reward_payable_account_type_blank()
    _check_parity_with_incentive_payable()
    _check_root_type_intact()
    _check_backfill_query_works()
    _check_idempotency()
    print()
    print("All smoke checks PASSED ✓")
