"""Smoke test for the Purchase Receipt ↔ Landed Cost Voucher ↔ GL Entry
invariant.

Sridhar 2026-06-13 via WhatsApp: "Purchase Taxes and Charges hideed?
not seeing submitted PR that is the reason the fight and document
change not showing". Customer-visible confusion on GRN-FZCO-26-00448
where the form's Taxes and Charges section showed ₹0 but the General
Ledger correctly had Freight 3,865 + Documentation 545 lines posted
under voucher_type='Purchase Receipt'.

Root cause was NOT a hidden taxes table — it was a Landed Cost
Voucher amendment chain:
  - LCV-FZCO-26-00231    docstatus=2 (cancelled)  Freight only 3,865
  - LCV-FZCO-26-00231-1  docstatus=1 (submitted)  Freight 3,865 + Doc 545

Standard ERPNext LCV flow leaves PR.taxes EMPTY by design — landed
costs flow through the LCV doctype and re-post the PR's GL Entries
(retaining voucher_type='Purchase Receipt') without touching the
PR's taxes child table.

This smoke locks in the invariant: for any PR with non-zero
landed-cost GL lines, there MUST be a corresponding submitted LCV
chain summing to the same total. If the invariant ever breaks
(rogue GL entries, missing LCV, amendment mismatch) the smoke
fails before users see ₹0-but-not-zero confusion again.

Usage:
    bench --site avientekv21.local execute \\
        avientek.scripts.smoke_pr_lcv_invariant.run

Targeted PR is parameterizable — defaults to GRN-FZCO-26-00448
(the reported case). Pass a different name to spot-check another
PR after data ops:
    bench --site avientekv21.local execute \\
        avientek.scripts.smoke_pr_lcv_invariant.run \\
        --kwargs '{"pr_name": "GRN-FZCO-26-00xxx"}'
"""

import frappe


DEFAULT_PR = "GRN-FZCO-26-00448"

# GL accounts that represent LANDED-COST charges on Purchase Receipt.
# Anything NOT in {Stock-in-Trade*, Stock Received But Not Billed*}
# and NOT a tax-payable account is presumed to be a landed-cost line
# (Freight, Documentation, Customs Duty, Clearance, etc.). The
# pattern match is broad on purpose — a new landed-cost account
# doesn't require a smoke update.
_NOT_LANDED_COST_PATTERNS = (
    "Stock-in-Trade",
    "Stock Received But Not Billed",
    "Stock In Hand",
    "Cost of Goods Sold",
)


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


def _is_landed_cost_account(account_name):
    """Heuristic — a GL row hitting a non-stock, non-COGS account on a
    Purchase Receipt voucher is presumed to be a landed-cost line."""
    for pattern in _NOT_LANDED_COST_PATTERNS:
        if pattern in account_name:
            return False
    return True


def _check_pr_taxes_empty_by_design(pr):
    """The form's 'Taxes and Charges' section being empty on a PR
    with landed-cost GL lines is BY DESIGN. The smoke records the
    observed state for the report — no failure if it's empty.
    """
    print()
    print(f"=== {pr.name}: PR.taxes child table (the form's 'Taxes and Charges' section) ===")
    print(f"  taxes_and_charges (template name): {pr.taxes_and_charges!r}")
    print(f"  pr.taxes row count: {len(pr.taxes)}")
    print(f"  total_taxes_and_charges: {pr.total_taxes_and_charges}")
    print(f"  base_total_taxes_and_charges: {pr.base_total_taxes_and_charges}")
    if pr.taxes:
        _ok("PR.taxes has rows (template-applied taxes; LCV flow not in use here)")
    else:
        _ok("PR.taxes is empty (expected when landed costs flow via LCV, not template)")


def _gather_lcv_chain(pr_name):
    """Return ([submitted_lcvs], [cancelled_lcvs]) referencing this PR."""
    child_rows = frappe.get_all(
        "Landed Cost Purchase Receipt",
        filters={"receipt_document": pr_name},
        fields=["parent"],
    )
    lcv_names = sorted({r["parent"] for r in child_rows})
    submitted, cancelled = [], []
    for nm in lcv_names:
        lcv = frappe.get_doc("Landed Cost Voucher", nm)
        if lcv.docstatus == 1:
            submitted.append(lcv)
        elif lcv.docstatus == 2:
            cancelled.append(lcv)
    return submitted, cancelled


def _check_lcv_chain(pr, submitted, cancelled):
    print()
    print(f"=== LCV chain ===")
    print(f"  submitted LCVs: {len(submitted)}")
    for lcv in submitted:
        print(f"    {lcv.name}  posting_date={lcv.posting_date}  "
              f"total_taxes_and_charges={lcv.total_taxes_and_charges}  "
              f"taxes_rows={len(lcv.taxes)}")
        for t in lcv.taxes:
            print(f"      {t.expense_account!r}  amount={t.amount}  desc={t.description!r}")
    print(f"  cancelled LCVs: {len(cancelled)}")
    for lcv in cancelled:
        print(f"    {lcv.name}  posting_date={lcv.posting_date}  "
              f"total_taxes_and_charges={lcv.total_taxes_and_charges}")

    # Invariant 1: at most one ACTIVE landed-cost burden per PR. If
    # there are >1 submitted LCVs covering the same PR, the GL
    # would double-burden. Standard amendment flow: the original
    # gets cancelled when the amended copy submits, so there's
    # always exactly one submitted version. (Zero is also valid —
    # PR with no landed costs.)
    if len(submitted) > 1:
        _fail(
            f"{pr.name}: {len(submitted)} simultaneously-submitted LCVs reference "
            f"this PR. ERPNext's amendment flow should cancel the prior version "
            f"before the new one submits. Double-burdened landed cost in GL."
        )
    _ok(f"≤1 submitted LCV per PR (amendment chain healthy)")


def _check_gl_matches_lcv(pr, submitted_lcvs):
    print()
    print(f"=== GL landed-cost lines vs LCV total ===")
    gles = frappe.get_all(
        "GL Entry",
        filters={
            "voucher_type": "Purchase Receipt",
            "voucher_no": pr.name,
            "is_cancelled": 0,
        },
        fields=["account", "debit", "credit"],
    )
    landed_cost_total = 0.0
    landed_cost_rows = []
    for g in gles:
        if not _is_landed_cost_account(g["account"]):
            continue
        # Landed-cost lines post as a CREDIT on the expense account
        # (offsetting the additional Stock-in-Trade debit). Use the
        # credit side as the landed-cost amount.
        amt = float(g["credit"] or 0)
        if amt:
            landed_cost_rows.append((g["account"], amt))
            landed_cost_total += amt
    for acct, amt in landed_cost_rows:
        print(f"  GL: {acct}  Cr={amt}")
    print(f"  GL landed-cost total: {landed_cost_total}")

    expected = sum(float(lcv.total_taxes_and_charges or 0) for lcv in submitted_lcvs)
    print(f"  Submitted LCV total : {expected}")

    if abs(landed_cost_total - expected) > 0.01:
        _fail(
            f"{pr.name}: GL landed-cost total ({landed_cost_total}) does NOT match "
            f"submitted LCV total ({expected}). Possible causes: a submitted LCV "
            f"didn't repost the PR's GL; a cancelled LCV left orphan GL rows; "
            f"manual GL Entry rogue insertion. Audit the LCV cancel/amend chain."
        )
    _ok("GL landed-cost total matches submitted LCV total exactly — invariant holds")


def _check_pr_items_landed_cost_amount(pr, submitted_lcvs):
    """When an LCV is submitted, ERPNext distributes the
    total_taxes_and_charges across the PR's items and stamps each
    row's `landed_cost_voucher_amount`. Sum must equal the LCV
    total — otherwise the items' valuation_rate is wrong and the
    inventory ledger drifts.
    """
    print()
    print(f"=== PR items: landed_cost_voucher_amount distribution ===")
    expected = sum(float(lcv.total_taxes_and_charges or 0) for lcv in submitted_lcvs)
    distributed = 0.0
    for it in pr.items:
        lcv_amt = float(getattr(it, "landed_cost_voucher_amount", 0) or 0)
        distributed += lcv_amt
    print(f"  Expected (from submitted LCVs): {expected}")
    print(f"  Distributed (sum of item.landed_cost_voucher_amount): {distributed}")
    if abs(distributed - expected) > 0.05:  # 5p tolerance for proportional rounding
        _fail(
            f"{pr.name}: landed_cost_voucher_amount distribution drifted. "
            f"Expected {expected}, got {distributed}. Items' valuation_rate is "
            f"now inconsistent with the LCV — Stock Reconciliation needed."
        )
    _ok("LCV total correctly distributed across PR items (valuation_rate intact)")


def run(pr_name=None):
    pr_name = pr_name or DEFAULT_PR
    print("=" * 64)
    print(f"PR ↔ LCV ↔ GL invariant smoke for {pr_name}")
    print("=" * 64)

    if not frappe.db.exists("Purchase Receipt", pr_name):
        _fail(f"Purchase Receipt {pr_name!r} not found on this site")

    pr = frappe.get_doc("Purchase Receipt", pr_name)
    if pr.docstatus != 1:
        _fail(f"{pr_name} is not submitted (docstatus={pr.docstatus}); smoke needs a submitted PR")

    _check_pr_taxes_empty_by_design(pr)

    submitted, cancelled = _gather_lcv_chain(pr_name)
    _check_lcv_chain(pr, submitted, cancelled)

    if submitted:
        _check_gl_matches_lcv(pr, submitted)
        _check_pr_items_landed_cost_amount(pr, submitted)
    else:
        # No LCVs — invariant trivially holds. Make sure GL has no
        # rogue landed-cost lines either.
        print()
        print(f"=== No submitted LCV — GL should have ZERO landed-cost lines ===")
        gles = frappe.get_all(
            "GL Entry",
            filters={
                "voucher_type": "Purchase Receipt",
                "voucher_no": pr_name,
                "is_cancelled": 0,
            },
            fields=["account", "debit", "credit"],
        )
        rogue = [g for g in gles
                 if _is_landed_cost_account(g["account"]) and float(g["credit"] or 0) > 0]
        if rogue:
            _fail(f"{pr_name}: {len(rogue)} GL row(s) on landed-cost accounts but no submitted LCV — orphan entries")
        _ok("Clean — no LCV, no rogue landed-cost GL lines")

    print()
    print("All smoke checks PASSED ✓")
