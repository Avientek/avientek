"""Smoke test for the Purchase Receipt 'Connections' panel showing
linked Landed Cost Vouchers.

Sridhar 2026-06-13 via WhatsApp on GRN-FZCO-26-00448 — the form's
Connections panel listed the label "Landed Cost Voucher" but with NO
count badge, so the user had no clickable path from the PR to the LCV
that posted the freight & documentation GL lines.

Root cause: ERPNext's PR dashboard config sets
`non_standard_fieldnames["Landed Cost Voucher"] = "receipt_document"`,
but `receipt_document` is on the CHILD doctype `Landed Cost Purchase
Receipt`, not on the LCV parent. Frappe's get_external_links runs

    frappe.db.count("Landed Cost Voucher", {"receipt_document": pr_name})

→ SQL "Unknown column 'receipt_document'" → swallowed → count=0 →
no badge.

avientek/__init__.py's `_patch_pr_dashboard_lcv_count` monkey-patches
`frappe.desk.notifications._get_linked_document_counts` to inject a
proper `internal_links_found` entry for LCVs found via the child-table
JOIN, with both count and clickable `names`.

This smoke confirms the patch is wired and behaves correctly across:
  (1) PR with a submitted LCV chain → badge count = number of
      non-cancelled LCVs, names list is populated.
  (2) PR with NO LCV → no LCV entry appended (no false-positive badge).
  (3) Non-PR doctype call → patch is a no-op (no foreign mutations).
  (4) Cancelled LCV in the chain is EXCLUDED from the count.
  (5) Stale broken `external_links_found` entry for LCV (count=0 from
      the upstream SQL error) is cleaned out so the UI doesn't render
      a duplicate disabled badge.

Usage:
    bench --site avientekv21.local execute \\
        avientek.scripts.smoke_pr_lcv_connections.run

Defaults to GRN-FZCO-26-00448 (Sridhar's reported case). Override:
    bench --site avientekv21.local execute \\
        avientek.scripts.smoke_pr_lcv_connections.run \\
        --kwargs '{"pr_name": "GRN-FZCO-26-00xxx"}'
"""

import frappe


DEFAULT_PR = "GRN-FZCO-26-00448"


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


def _get_lcv_entry(info):
    """Pull the Landed Cost Voucher entry from the result of
    _get_linked_document_counts (after the avientek patch). Returns
    (entry_dict_or_None, location) where location is 'internal' or
    'external' or None."""
    inner = info.get("count") or {}
    for entry in inner.get("internal_links_found") or []:
        if entry.get("doctype") == "Landed Cost Voucher":
            return entry, "internal"
    for entry in inner.get("external_links_found") or []:
        if entry.get("doctype") == "Landed Cost Voucher":
            return entry, "external"
    return None, None


def _expected_lcv_names(pr_name):
    """The set of LCV names the patch SHOULD surface — non-cancelled
    LCVs referencing this PR via the child Landed Cost Purchase Receipt
    table.
    """
    rows = frappe.db.sql(
        """
        SELECT DISTINCT lcv.name
        FROM `tabLanded Cost Voucher` lcv
        INNER JOIN `tabLanded Cost Purchase Receipt` lpr
            ON lpr.parent = lcv.name
        WHERE lpr.receipt_document = %s
          AND lcv.docstatus < 2
        ORDER BY lcv.name
        """,
        (pr_name,),
    )
    return [r[0] for r in rows]


def _cancelled_lcv_names(pr_name):
    rows = frappe.db.sql(
        """
        SELECT DISTINCT lcv.name
        FROM `tabLanded Cost Voucher` lcv
        INNER JOIN `tabLanded Cost Purchase Receipt` lpr
            ON lpr.parent = lcv.name
        WHERE lpr.receipt_document = %s
          AND lcv.docstatus = 2
        ORDER BY lcv.name
        """,
        (pr_name,),
    )
    return [r[0] for r in rows]


def _check_patch_wired():
    print()
    print("=== Patch wired: notifications._get_linked_document_counts replaced ===")
    from frappe.desk import notifications

    fn = getattr(notifications, "_get_linked_document_counts", None)
    if fn is None:
        _fail(
            "frappe.desk.notifications._get_linked_document_counts is missing — "
            "Frappe version drift; rewire the monkey-patch."
        )
    # The patched closure's qualname will start with '_patch_pr_dashboard_lcv_count'
    qualname = getattr(fn, "__qualname__", "") or ""
    if "_patch_pr_dashboard_lcv_count" not in qualname:
        _fail(
            f"_get_linked_document_counts qualname is {qualname!r} — "
            "patch did not install (avientek/__init__.py didn't run, or "
            "Frappe reloaded the module after import)."
        )
    _ok(f"patched (qualname: {qualname})")


def _check_pr_with_lcv(pr_name):
    print()
    print(f"=== PR {pr_name} — LCV chain via patched Connections ===")
    from frappe.desk.notifications import _get_linked_document_counts

    expected_names = _expected_lcv_names(pr_name)
    cancelled = _cancelled_lcv_names(pr_name)

    print(f"  Expected non-cancelled LCV names (truth from SQL): {expected_names}")
    print(f"  Cancelled LCV names (must NOT appear): {cancelled}")

    if not expected_names:
        _fail(
            f"{pr_name}: SQL says no non-cancelled LCVs exist — this PR "
            "isn't a valid fixture for the smoke. Pass a different "
            "pr_name (one with at least one submitted LCV)."
        )

    info = _get_linked_document_counts("Purchase Receipt", pr_name)
    entry, where = _get_lcv_entry(info)

    if not entry:
        _fail(
            f"{pr_name}: Connections has NO 'Landed Cost Voucher' entry "
            f"in either internal_links_found or external_links_found. "
            f"Patch failed to inject."
        )
    if where != "internal":
        _fail(
            f"{pr_name}: LCV entry found but in {where!r}, not 'internal'. "
            "The frontend renders a clickable name list only for "
            "internal_links_found — external_links_found shows count only "
            "and the count's filter is broken (the very bug we're fixing)."
        )

    _ok(f"LCV entry surfaced in internal_links_found")

    if entry.get("count") != len(expected_names):
        _fail(
            f"{pr_name}: badge count = {entry.get('count')}, expected "
            f"{len(expected_names)}."
        )
    _ok(f"badge count = {entry['count']}")

    got_names = set(entry.get("names") or [])
    want_names = set(expected_names)
    if got_names != want_names:
        _fail(
            f"{pr_name}: clickable names {sorted(got_names)} != expected "
            f"{sorted(want_names)}."
        )
    _ok(f"clickable names match: {sorted(got_names)}")

    # Cancelled LCV must NOT bleed in
    for c in cancelled:
        if c in got_names:
            _fail(
                f"{pr_name}: cancelled LCV {c!r} leaked into Connections "
                "badge. Patch's docstatus filter is wrong."
            )
    _ok("cancelled LCVs correctly excluded")

    # The stale broken external_links_found entry (count=0 from SQL error)
    # must have been pruned by the patch
    inner = info.get("count") or {}
    for ext in inner.get("external_links_found") or []:
        if ext.get("doctype") == "Landed Cost Voucher":
            _fail(
                f"{pr_name}: stale 'Landed Cost Voucher' entry still in "
                "external_links_found (count={ext.get('count')}). UI would "
                "render two badges. Patch must prune."
            )
    _ok("stale external_links_found entry for LCV pruned")


def _check_pr_without_lcv():
    print()
    print("=== PR with NO LCV — patch must NOT inject false-positive ===")
    # Find an arbitrary submitted PR that has zero LCV references
    pr_no_lcv = frappe.db.sql(
        """
        SELECT pr.name
        FROM `tabPurchase Receipt` pr
        LEFT JOIN `tabLanded Cost Purchase Receipt` lpr
            ON lpr.receipt_document = pr.name
        WHERE pr.docstatus = 1 AND lpr.parent IS NULL
        LIMIT 1
        """,
    )
    if not pr_no_lcv:
        print("  (skipped — no LCV-free submitted PR on site to test against)")
        return
    target = pr_no_lcv[0][0]
    print(f"  Using {target}")

    from frappe.desk.notifications import _get_linked_document_counts

    info = _get_linked_document_counts("Purchase Receipt", target)
    inner = info.get("count") or {}
    for entry in inner.get("internal_links_found") or []:
        if entry.get("doctype") == "Landed Cost Voucher":
            _fail(
                f"{target}: patch injected a 'Landed Cost Voucher' entry "
                f"for a PR with no LCV — false-positive badge."
            )
    _ok(f"{target}: no spurious LCV entry — patch correctly inert when chain empty")


def _check_non_pr_passthrough():
    print()
    print("=== Non-PR doctype — patch must pass through unchanged ===")
    # Pick a doctype on the site that has dashboard_data and a sample doc
    sample = frappe.db.sql(
        "SELECT name FROM `tabSales Invoice` WHERE docstatus = 1 LIMIT 1"
    )
    if not sample:
        print("  (skipped — no submitted Sales Invoice on this site)")
        return
    si = sample[0][0]

    from frappe.desk.notifications import _get_linked_document_counts

    info = _get_linked_document_counts("Sales Invoice", si)
    inner = info.get("count") or {}
    # Sales Invoice dashboard does not advertise Landed Cost Voucher,
    # so we should NOT find one in either bucket
    for entry in inner.get("internal_links_found") or []:
        if entry.get("doctype") == "Landed Cost Voucher":
            _fail(
                f"{si}: patch leaked LCV into a Sales Invoice's Connections. "
                "Patch must scope itself to Purchase Receipt only."
            )
    _ok(f"Sales Invoice {si}: no LCV injection — patch correctly PR-scoped")


def run(pr_name=None):
    pr_name = pr_name or DEFAULT_PR
    print("=" * 64)
    print(f"PR Connections 'Landed Cost Voucher' badge smoke for {pr_name}")
    print("=" * 64)

    if not frappe.db.exists("Purchase Receipt", pr_name):
        _fail(f"Purchase Receipt {pr_name!r} not found on this site")

    _check_patch_wired()
    _check_pr_with_lcv(pr_name)
    _check_pr_without_lcv()
    _check_non_pr_passthrough()

    print()
    print("All smoke checks PASSED ✓")
