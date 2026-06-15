"""Smoke for the 2026-06-15 direct-cancel from Approved Quotation.

Sridhar follow-up: margin-satisfied (Approved) Quotation now has a
1-click Cancel path that bypasses the 2-level L1/L2 review chain.
Patch: avientek.patches.add_quotation_direct_cancel_from_approved.

What the smoke verifies:

  A. The 4 new transitions exist on the active workflow:
       Approved --[Cancel]--> Cancelled  (Sales Support L2)
       Approved --[Cancel]--> Cancelled  (GM-CS)
       Approved --[Cancel]--> Cancelled  (GM)
       Approved --[Cancel]--> Cancelled  (System Manager)

  B. The EXISTING 2-level review chain is still intact (regression
     guard) — in-flight cancellation requests must continue to work:
       Approved          --[Request Cancellation]--> Cancellation Requested  (Sales Support L2)
       Approved          --[Request Cancellation]--> Cancellation Requested  (GM-CS)
       Cancellation Requested --[Approve Cancellation Level 1]--> Cancellation L2 Pending  (GM-CS)
       Cancellation L2 Pending --[Approve Cancellation Level 2]--> Cancelled  (GM)

  C. Patch is idempotent — re-running adds zero rows.

  D. doc_status delta sanity: the new transition goes from
     Approved.doc_status=1 → Cancelled.doc_status=2 (forward — Frappe
     accepts this; if the state docstatuses were flipped the
     workflow.save would crash with "Submitted Document cannot be
     converted back to draft").

Usage:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_quotation_direct_cancel_from_approved.run
"""

import frappe


_ACTIVE_WORKFLOW = "Quotation Approval Workflow Avientek (V3)"
_FROM_STATE = "Approved"
_ACTION = "Cancel"
_TO_STATE = "Cancelled"
_ALLOWED_ROLES = ("Sales Support L2", "GM-CS", "GM", "System Manager")

# The 2-level chain that MUST stay intact for in-flight cancellations.
_REQUIRED_LEGACY = [
    ("Approved", "Request Cancellation", "Cancellation Requested", "Sales Support L2"),
    ("Approved", "Request Cancellation", "Cancellation Requested", "GM-CS"),
    ("Cancellation Requested", "Approve Cancellation Level 1",
     "Cancellation L2 Pending", "GM-CS"),
    ("Cancellation L2 Pending", "Approve Cancellation Level 2",
     "Cancelled", "GM"),
]


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


def _check_new_transitions():
    print()
    print("=== A. 4 new direct-cancel transitions ===")
    rows = frappe.get_all(
        "Workflow Transition",
        filters={
            "parent": _ACTIVE_WORKFLOW,
            "state": _FROM_STATE,
            "action": _ACTION,
            "next_state": _TO_STATE,
        },
        fields=["allowed"],
    )
    found_roles = {r["allowed"] for r in rows}
    missing = [r for r in _ALLOWED_ROLES if r not in found_roles]
    if missing:
        _fail(
            f"Missing direct-cancel transition for roles: {missing}. "
            f"Found: {sorted(found_roles)}"
        )
    for role in _ALLOWED_ROLES:
        _ok(f"Approved --[Cancel]--> Cancelled  ({role})")


def _check_legacy_chain_intact():
    print()
    print("=== B. 2-level review chain still intact (regression guard) ===")
    rows = frappe.get_all(
        "Workflow Transition",
        filters={"parent": _ACTIVE_WORKFLOW},
        fields=["state", "action", "next_state", "allowed"],
    )
    existing = {(r["state"], r["action"], r["next_state"], r["allowed"]) for r in rows}
    missing = [t for t in _REQUIRED_LEGACY if t not in existing]
    if missing:
        _fail(
            f"Legacy cancellation chain missing {len(missing)} transition(s):\n    "
            + "\n    ".join(repr(t) for t in missing)
        )
    for t in _REQUIRED_LEGACY:
        s, a, ns, who = t
        _ok(f"{s:24s} --[{a:30s}]--> {ns:24s} ({who})")


def _check_idempotency():
    print()
    print("=== C. Patch is idempotent on re-run ===")
    from avientek.patches.add_quotation_direct_cancel_from_approved import (
        _ensure_transitions,
    )
    added = _ensure_transitions()
    if added != 0:
        _fail(
            f"Re-running the patch added {added} new transitions — "
            "should be 0 (already inserted)"
        )
    _ok("Re-run inserts 0 rows — idempotent")


def _check_docstatus_delta():
    print()
    print("=== D. doc_status delta: Approved(1) → Cancelled(2) is forward ===")
    rows = frappe.db.sql(
        """
        SELECT state, doc_status FROM `tabWorkflow Document State`
        WHERE parent = %s AND state IN (%s, %s)
        """,
        (_ACTIVE_WORKFLOW, _FROM_STATE, _TO_STATE),
        as_dict=True,
    )
    if len(rows) != 2:
        _fail(f"Expected 2 state rows (Approved + Cancelled), got {rows}")
    by_state = {r["state"]: int(r["doc_status"]) for r in rows}
    if by_state.get(_FROM_STATE) != 1:
        _fail(f"{_FROM_STATE}.doc_status = {by_state.get(_FROM_STATE)}, expected 1")
    if by_state.get(_TO_STATE) != 2:
        _fail(f"{_TO_STATE}.doc_status = {by_state.get(_TO_STATE)}, expected 2")
    _ok(f"{_FROM_STATE}.doc_status=1 → {_TO_STATE}.doc_status=2 (forward)")


def _check_no_dup_transitions():
    print()
    print("=== E. No duplicate (state, action, next_state, role) rows ===")
    from collections import Counter
    rows = frappe.get_all(
        "Workflow Transition",
        filters={"parent": _ACTIVE_WORKFLOW},
        fields=["state", "action", "next_state", "allowed"],
    )
    counts = Counter((r["state"], r["action"], r["next_state"], r["allowed"]) for r in rows)
    # Restrict the duplicate check to our 4 new tuples (don't flag
    # unrelated duplicates that may have existed before this patch).
    expected_new = {
        (_FROM_STATE, _ACTION, _TO_STATE, role) for role in _ALLOWED_ROLES
    }
    dups = [(t, n) for t, n in counts.items() if t in expected_new and n > 1]
    if dups:
        _fail(f"Duplicate direct-cancel rows: {dups}")
    _ok("No duplicates among the 4 new transitions")


def run():
    print("=" * 64)
    print("Avientek smoke: direct Cancel from Approved Quotation")
    print("=" * 64)
    _check_new_transitions()
    _check_legacy_chain_intact()
    _check_idempotency()
    _check_docstatus_delta()
    _check_no_dup_transitions()
    print()
    print("All smoke checks PASSED ✓")
