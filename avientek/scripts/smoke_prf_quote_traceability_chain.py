"""Smoke for the 2026-06-15 PRF Enhancement §2 — Intracompany Quote
Traceability Chain.

Sridhar/Jithin 2026-06-15 (PRF Enhancement doc): "The system
currently treats these documents as isolated records. To display
costing data (like margins or incentives) on the PRF, the system
needs to 'see through' the layers of intercompany documentation to
reach the original source: the Quotation."

The doc's stated chain:
  Payment Request Form (PRF)
    --> Intercompany Purchase Order (PO)
      --> Linked Sales Order (via PO Item.sales_order)
        --> Original Sales Order (via Linked SO.po_no)
          --> Original Quotation (via Original SO Item.prevdoc_docname)

This smoke covers:

  Structural (3)
    A. _get_quotation_for_po still exists and accepts None
    B. _resolve_quotation_through_so_chain exists as the recursive
       walker
    C. The two call-sites (lines ~3458 and ~5134) still call
       _get_quotation_for_po (no caller signature drift)

  Behavioural (6) — uses synthetic Sales Order / Quotation records
  inserted in a transaction we roll back at the end. Avoids any
  permanent DB state.

    1. STANDARD CHAIN (1-hop): SO with prevdoc_docname → resolver
       returns the Quotation. Existing Rahul 2026-05-22 behavior
       preserved.
    2. INTERCOMPANY CHAIN (2-hop): Linked SO without prevdoc_docname
       but WITH po_no pointing to Original SO → walker recurses,
       returns the Quotation from Original SO.
    3. DEEP INTERCOMPANY (3-hop): for robustness — Linked SO --po_no
       --> Mid SO --po_no--> Original SO with Quote. Walker reaches
       the Quote.
    4. CHAIN BREAKS — Linked SO has no prevdoc_docname AND po_no is
       blank → resolver returns None (no false-positive).
    5. CYCLE GUARD — SO_A.po_no=SO_B, SO_B.po_no=SO_A, neither has
       prevdoc → resolver returns None (no infinite loop).
    6. DEPTH BOUND — chain longer than 5 hops → resolver returns
       None (bail rather than walk forever on pathological data).

Usage:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_prf_quote_traceability_chain.run
"""

import frappe


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


# ----------------------------------------------------------------------
# Structural checks
# ----------------------------------------------------------------------


def _check_structural():
    print()
    print("=== A/B/C. Resolver functions + call-site integrity ===")

    from avientek.avientek.doctype.payment_request_form.payment_request_form import (
        _get_quotation_for_po,
        _resolve_quotation_through_so_chain,
    )

    # A. accepts None / empty string without crashing
    for arg in (None, "", 0, False):
        try:
            r = _get_quotation_for_po(arg)
        except Exception as e:
            _fail(f"_get_quotation_for_po({arg!r}) crashed: {e}")
        if r is not None:
            _fail(f"_get_quotation_for_po({arg!r}) returned {r!r}, expected None")
    _ok("_get_quotation_for_po accepts None / empty / falsy without crash")

    # B. recursive walker exists and is independently callable
    if not callable(_resolve_quotation_through_so_chain):
        _fail("_resolve_quotation_through_so_chain not callable")
    if _resolve_quotation_through_so_chain(None) is not None:
        _fail("_resolve_quotation_through_so_chain(None) should return None")
    _ok("_resolve_quotation_through_so_chain exists as recursive walker")

    # C. Both known call-sites still reference _get_quotation_for_po
    # (no other code path forks the chain logic).
    import re
    path = frappe.get_app_path(
        "avientek", "avientek", "doctype", "payment_request_form",
        "payment_request_form.py",
    )
    with open(path) as f:
        src = f.read()
    calls = re.findall(r"_get_quotation_for_po\(", src)
    # Expect: 1 definition + 2 call-sites = 3 occurrences
    if len(calls) < 3:
        _fail(
            f"Expected ≥3 occurrences of _get_quotation_for_po( "
            f"(1 def + 2 callers), found {len(calls)}. Caller may have "
            "been deleted or renamed — Brand Summary rendering breaks."
        )
    _ok(f"_get_quotation_for_po referenced {len(calls)}× — call-sites intact")


# ----------------------------------------------------------------------
# Behavioural — synthetic in-transaction fixtures
# ----------------------------------------------------------------------


def _stub_so(name, prevdoc_docname=None, po_no=None):
    """Insert a minimal Sales Order + one SO Item directly via SQL so
    we don't trigger Frappe's full validate chain (which would demand
    Company, Customer, Currency, etc). The resolver only reads two
    fields — we set just those.

    Rollback at end-of-smoke clears every row.
    """
    # Parent Sales Order
    frappe.db.sql(
        """
        INSERT INTO `tabSales Order`
            (name, docstatus, owner, creation, modified, modified_by,
             po_no, naming_series, status, transaction_date)
        VALUES (%s, 1, 'Administrator', NOW(), NOW(), 'Administrator',
                %s, 'SO-SMOKE-', 'To Deliver and Bill', CURRENT_DATE())
        """,
        (name, po_no or ""),
    )
    # Child SO Item (mandatory parent linkage)
    frappe.db.sql(
        """
        INSERT INTO `tabSales Order Item`
            (name, parent, parenttype, parentfield, idx, docstatus,
             owner, creation, modified, modified_by,
             prevdoc_docname)
        VALUES (%s, %s, 'Sales Order', 'items', 1, 1,
                'Administrator', NOW(), NOW(), 'Administrator', %s)
        """,
        (f"SOI-{name}", name, prevdoc_docname or ""),
    )


def _stub_quote(name):
    """Insert a minimal Quotation so exists() returns True."""
    frappe.db.sql(
        """
        INSERT INTO `tabQuotation`
            (name, docstatus, owner, creation, modified, modified_by,
             naming_series, status, transaction_date)
        VALUES (%s, 1, 'Administrator', NOW(), NOW(), 'Administrator',
                'QN-SMOKE-', 'Submitted', CURRENT_DATE())
        """,
        (name,),
    )


def _check_behavioural():
    from avientek.avientek.doctype.payment_request_form.payment_request_form import (
        _resolve_quotation_through_so_chain,
    )

    print()
    print("=== Behavioural: 6 chain shapes via synthetic SO/Quote rows ===")
    print("    (transaction rolled back at end — no permanent rows)")

    # Frappe has no cache.clear_value for raw SQL inserts; the resolver
    # uses frappe.db.get_value which reads from the same transaction.
    try:
        # ----- shared quote -----
        _stub_quote("QN-SMOKE-001")

        # ----- Case 1 — STANDARD: SO --prevdoc--> Quote -----
        _stub_so("SO-SMOKE-STD-001", prevdoc_docname="QN-SMOKE-001")
        got = _resolve_quotation_through_so_chain("SO-SMOKE-STD-001")
        if got != "QN-SMOKE-001":
            _fail(f"Case 1 standard chain returned {got!r}, expected 'QN-SMOKE-001'")
        _ok("Case 1 — Standard (SO → prevdoc_docname → Quote): RESOLVED")

        # ----- Case 2 — INTERCOMPANY 2-hop -----
        # Original SO (has the Quote)
        _stub_so("SO-SMOKE-ORIG-002", prevdoc_docname="QN-SMOKE-001")
        # Linked SO (no Quote, points to Original via po_no)
        _stub_so("SO-SMOKE-LINK-002", po_no="SO-SMOKE-ORIG-002")
        got = _resolve_quotation_through_so_chain("SO-SMOKE-LINK-002")
        if got != "QN-SMOKE-001":
            _fail(f"Case 2 intercompany chain returned {got!r}, expected 'QN-SMOKE-001'")
        _ok("Case 2 — Intercompany 2-hop (Linked SO → po_no → Original → Quote): RESOLVED")

        # ----- Case 3 — DEEP INTERCOMPANY 3-hop -----
        _stub_so("SO-SMOKE-ORIG-003", prevdoc_docname="QN-SMOKE-001")
        _stub_so("SO-SMOKE-MID-003", po_no="SO-SMOKE-ORIG-003")
        _stub_so("SO-SMOKE-LINK-003", po_no="SO-SMOKE-MID-003")
        got = _resolve_quotation_through_so_chain("SO-SMOKE-LINK-003")
        if got != "QN-SMOKE-001":
            _fail(f"Case 3 3-hop chain returned {got!r}, expected 'QN-SMOKE-001'")
        _ok("Case 3 — Deep 3-hop (Linked → Mid → Original → Quote): RESOLVED")

        # ----- Case 4 — CHAIN BREAKS -----
        _stub_so("SO-SMOKE-BROKEN-004", prevdoc_docname="", po_no="")
        got = _resolve_quotation_through_so_chain("SO-SMOKE-BROKEN-004")
        if got is not None:
            _fail(f"Case 4 broken chain returned {got!r}, expected None")
        _ok("Case 4 — Broken chain (no prevdoc, no po_no): None (no false-positive)")

        # ----- Case 5 — CYCLE GUARD -----
        _stub_so("SO-SMOKE-CYCLE-A", po_no="SO-SMOKE-CYCLE-B")
        _stub_so("SO-SMOKE-CYCLE-B", po_no="SO-SMOKE-CYCLE-A")
        got = _resolve_quotation_through_so_chain("SO-SMOKE-CYCLE-A")
        if got is not None:
            _fail(
                f"Case 5 cycle should return None (no Quote in chain), got {got!r}"
            )
        _ok("Case 5 — Cycle (A→B→A): None (no infinite loop)")

        # ----- Case 6 — DEPTH BOUND -----
        # Chain of 7 SOs, only the LAST has the Quote. Depth limit is
        # 5, so walker bails before reaching the Quote.
        _stub_so("SO-SMOKE-DEEP-7", prevdoc_docname="QN-SMOKE-001")
        prior = "SO-SMOKE-DEEP-7"
        for i in range(6, 0, -1):
            cur = f"SO-SMOKE-DEEP-{i}"
            _stub_so(cur, po_no=prior)
            prior = cur
        # Now SO-SMOKE-DEEP-1 → 2 → 3 → 4 → 5 → 6 → 7 (Quote at 7).
        # 6 hops to reach 7 — walker depth limit (5) bails.
        got = _resolve_quotation_through_so_chain("SO-SMOKE-DEEP-1")
        if got is not None:
            _fail(
                f"Case 6 chain > depth limit should return None, got {got!r}. "
                "Depth bound (5) not enforced."
            )
        _ok("Case 6 — Chain longer than depth bound (>5 hops): None (bail)")

    finally:
        # Roll back EVERYTHING we inserted — synthetic rows must not
        # survive the smoke. frappe.db.rollback() works because we did
        # all inserts inside this transaction.
        frappe.db.rollback()


def run():
    print("=" * 64)
    print("Avientek smoke: PRF Enhancement §2 — Quote Traceability Chain")
    print("=" * 64)
    _check_structural()
    _check_behavioural()
    print()
    print("All smoke checks PASSED ✓")
