"""Smoke test for PRF Payment Type behaviors:
   - Pay
   - Internal Transfer
   - Advance Pay

Verifies field visibility (depends_on), property setters, JS button gating,
and the 2026-05-07 fix where Pay's "Get Purchase Invoice" no longer
auto-pulls Purchase Orders (commit 36a4aa4).

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_payment_types.run
"""
from __future__ import annotations

import os

import frappe


APP_PATH = frappe.get_app_path("avientek")
PRF_JS = os.path.join(
    APP_PATH, "avientek", "doctype", "payment_request_form",
    "payment_request_form.js",
)
PRF_PY = os.path.join(
    APP_PATH, "avientek", "doctype", "payment_request_form",
    "payment_request_form.py",
)


def _hr(t):
    return "\n" + "─" * 70 + f"\n{t}\n" + "─" * 70


def _check(label, ok, detail=""):
    flag = "OK  " if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  {flag}  {label}{suffix}")
    return 1 if ok else 0


def _meta_field(meta, fieldname):
    for f in meta.fields:
        if f.fieldname == fieldname:
            return f
    return None


def _ps_value(field_name, prop):
    name = f"Payment Request Form-{field_name}-{prop}"
    if not frappe.db.exists("Property Setter", name):
        return None
    return frappe.db.get_value("Property Setter", name, "value")


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def run():
    print("=" * 70)
    print("PRF PAYMENT TYPE SMOKE — Pay / Internal Transfer / Advance Pay")
    print(f"site: {frappe.local.site}")
    print("=" * 70)

    pass_n = 0
    fail_n = 0

    meta = frappe.get_meta("Payment Request Form", cached=False)
    js = _read(PRF_JS)
    py = _read(PRF_PY)

    # ──────────────────────────────────────────────────────────
    # SUITE 1: Pay
    # ──────────────────────────────────────────────────────────
    print(_hr("[Pay] Payment Type = 'Pay'"))

    rs = _meta_field(meta, "reference_section")
    pm = _meta_field(meta, "payment_mode")
    party = _meta_field(meta, "party")
    party_type = _meta_field(meta, "party_type")

    rs_dep = (rs.depends_on or "") if rs else ""
    pm_dep = (pm.depends_on or "") if pm else ""

    score = 0
    score += _check(
        "reference_section depends_on includes 'Pay'",
        '"Pay"' in rs_dep,
        rs_dep.strip(),
    )
    score += _check(
        "payment_mode depends_on includes 'Pay'",
        '"Pay"' in pm_dep,
        pm_dep.strip(),
    )
    score += _check(
        "party visible for Pay (depends_on != Internal Transfer only)",
        bool(party) and (
            not party.depends_on or '!="Internal Transfer"' in (party.depends_on or "")
            or "Internal Transfer" not in (party.depends_on or "")
        ),
        (party.depends_on or "<no depends_on>") if party else "MISSING",
    )
    score += _check(
        "party_type visible for Pay",
        bool(party_type) and (
            not party_type.depends_on
            or "Internal Transfer" not in (party_type.depends_on or "")
        ),
        (party_type.depends_on or "<no depends_on>") if party_type else "MISSING",
    )

    # Property setter equivalents (these are what actually take effect on
    # production after fixture sync — DocField .depends_on is just the JSON
    # baseline)
    rs_ps = _ps_value("reference_section", "depends_on") or ""
    pm_ps = _ps_value("payment_mode", "depends_on") or ""
    score += _check(
        "Property Setter: reference_section.depends_on includes 'Pay'",
        '"Pay"' in rs_ps,
        rs_ps,
    )
    score += _check(
        "Property Setter: payment_mode.depends_on includes 'Pay'",
        '"Pay"' in pm_ps,
        pm_ps,
    )

    # The 2026-05-07 fix: Get Purchase Invoice no longer pulls POs
    py_no_po_pollution = (
        "if args.get(\"reference_doctype\") == \"Purchase Invoice\":\n"
        "        po_rows = _get_outstanding_purchase_orders(args)"
    ) not in py
    score += _check(
        "Pay flow: Get Purchase Invoice does NOT auto-fetch POs (commit 36a4aa4)",
        py_no_po_pollution,
        "auto-PO block removed" if py_no_po_pollution else "auto-PO block STILL PRESENT",
    )

    pass_n += score
    fail_n += 7 - score

    # ──────────────────────────────────────────────────────────
    # SUITE 2: Internal Transfer
    # ──────────────────────────────────────────────────────────
    print(_hr("[Internal Transfer] Payment Type = 'Internal Transfer'"))

    rb = _meta_field(meta, "receiving_bank")
    rb_dep = (rb.depends_on or "") if rb else ""
    sec_currency_totals = _meta_field(meta, "section_break_mnon")
    ct_dep = (sec_currency_totals.depends_on or "") if sec_currency_totals else ""

    score = 0
    score += _check(
        "receiving_bank shown for Internal Transfer",
        bool(rb) and "Internal Transfer" in rb_dep,
        rb_dep.strip(),
    )
    score += _check(
        "Currency Totals section hidden for Internal Transfer",
        bool(sec_currency_totals) and 'payment_type!="Internal Transfer"' in ct_dep,
        ct_dep.strip(),
    )
    score += _check(
        "reference_section hidden for Internal Transfer",
        "Internal Transfer" not in rs_dep,
        rs_dep.strip(),
    )
    score += _check(
        "payment_mode hidden for Internal Transfer",
        "Internal Transfer" not in pm_dep,
        pm_dep.strip(),
    )

    # JS check: Combined PDF button gated on Internal Transfer too
    has_it_combined = (
        '"Internal Transfer"' in js
        and 'Combined PDF' in js
        and '["Pay", "Advance Pay", "Internal Transfer"]' in js
    )
    score += _check(
        "JS: Download Combined PDF button enabled for Internal Transfer",
        has_it_combined,
        "found gating: Pay/Advance Pay/Internal Transfer",
    )

    # JS check: Internal Transfer auto-update issued/receiving amount
    has_it_xrate = (
        'frm.doc.payment_type === "Internal Transfer"' in js
        and 'transfer_exchange_rate' in js
    )
    score += _check(
        "JS: Internal Transfer exchange-rate handlers present",
        has_it_xrate,
    )

    pass_n += score
    fail_n += 6 - score

    # ──────────────────────────────────────────────────────────
    # SUITE 3: Advance Pay
    # ──────────────────────────────────────────────────────────
    print(_hr("[Advance Pay] Payment Type = 'Advance Pay'"))

    score = 0
    score += _check(
        "reference_section depends_on includes 'Advance Pay'",
        "Advance Pay" in rs_dep,
        rs_dep.strip(),
    )
    score += _check(
        "Property Setter: reference_section includes 'Advance Pay'",
        "Advance Pay" in rs_ps,
        rs_ps,
    )
    score += _check(
        "payment_mode depends_on includes 'Advance Pay'",
        "Advance Pay" in pm_dep,
        pm_dep.strip(),
    )
    score += _check(
        "Property Setter: payment_mode includes 'Advance Pay'",
        "Advance Pay" in pm_ps,
        pm_ps,
    )

    # The Advance Pay-specific PO picker endpoint
    has_po_endpoint = (
        "def get_open_purchase_orders_for_party" in py
        and "@frappe.whitelist()" in py
    )
    score += _check(
        "Endpoint get_open_purchase_orders_for_party exists",
        has_po_endpoint,
    )

    # JS gating: Get Open Purchase Orders button only on Advance Pay drafts
    has_get_po_btn = (
        '"Get Open Purchase Orders"' in js
        and 'frm.doc.payment_type === "Advance Pay"' in js
    )
    score += _check(
        "JS: 'Get Open Purchase Orders' button gated on Advance Pay",
        has_get_po_btn,
    )

    # Hide redundant advance fields
    cust_amt_hidden = _ps_value("custom_advance_amount", "hidden") in ("1", 1, True)
    cust_ref_hidden = _ps_value("custom_advance_reference", "hidden") in ("1", 1, True)
    score += _check(
        "Property Setter: custom_advance_amount hidden",
        cust_amt_hidden,
    )
    score += _check(
        "Property Setter: custom_advance_reference hidden",
        cust_ref_hidden,
    )

    # Combined PDF for Advance Pay
    has_ap_combined = '"Advance Pay"' in js and 'Combined PDF' in js
    score += _check(
        "JS: Download Combined PDF button enabled for Advance Pay",
        has_ap_combined,
    )

    pass_n += score
    fail_n += 9 - score

    # ──────────────────────────────────────────────────────────
    # Summary
    # ──────────────────────────────────────────────────────────
    total = pass_n + fail_n
    print("\n" + "=" * 70)
    if fail_n == 0:
        print(f"  ✅  ALL {total} CHECKS PASSED — Pay / IT / Advance Pay")
    else:
        print(f"  ❌  {fail_n}/{total} FAILED")
    print("=" * 70)

    return {
        "pass": pass_n,
        "fail": fail_n,
        "total": total,
    }
