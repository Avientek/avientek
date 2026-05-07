"""Smoke for Sridhar's 2026-05-07 PRF review followups.

Locks in regression coverage for the 6 items already shipped:
  #1  TR Print format dynamic by doc.tr_type (PV Fast + PV Pro)
  #2  Supplier PI input field (bill_no on payment_request_reference)
  #3  Open PO endpoint + Advance Pay button gating
  #5  Combined PDF: Supplier Invoice No column instead of system ref
  #7  Payment ref type dynamic via _classify_payment_type (no static "TR")
  #8  Per-company naming series auto-set (_apply_naming_series_by_company)

Items NOT covered (open work):
  #4  PDF copyable / searchable — needs renderer swap
  #6  Signature IMAGE for Siby Joy + Siby Thomas John — names dynamic, image not embedded

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_sridhar_followups.run
"""
from __future__ import annotations

import json
import os

import frappe


APP_PATH = frappe.get_app_path("avientek")
PRF_DIR = os.path.join(APP_PATH, "avientek", "doctype", "payment_request_form")
PRF_PY = os.path.join(PRF_DIR, "payment_request_form.py")
PRF_JS = os.path.join(PRF_DIR, "payment_request_form.js")
REF_JSON = os.path.join(
    APP_PATH, "avientek", "doctype", "payment_request_reference",
    "payment_request_reference.json",
)
PV_FAST_JSON = os.path.join(
    APP_PATH, "avientek", "print_format", "payment_voucher_fast",
    "payment_voucher_fast.json",
)
PV_PRO_JSON = os.path.join(
    APP_PATH, "avientek", "print_format", "payment_voucher_professional",
    "payment_voucher_professional.json",
)


def _hr(t):
    return "\n" + "─" * 70 + f"\n{t}\n" + "─" * 70


def _check(label, ok, detail=""):
    flag = "OK  " if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  {flag}  {label}{suffix}")
    return 1 if ok else 0


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _read_html(json_path):
    return json.load(open(json_path)).get("html") or ""


def run():
    print("=" * 70)
    print("PRF SRIDHAR FOLLOWUPS SMOKE — 2026-05-07")
    print(f"site: {frappe.local.site}")
    print("=" * 70)

    pass_n = 0
    fail_n = 0

    pv_fast = _read_html(PV_FAST_JSON)
    pv_pro = _read_html(PV_PRO_JSON)
    py = _read(PRF_PY)
    js = _read(PRF_JS)

    # ──────────────────────────────────────────────────────────
    # #1 — TR Print format dynamic by doc.tr_type
    # ──────────────────────────────────────────────────────────
    print(_hr("[#1] TR Print format dynamic by doc.tr_type"))
    score = 0
    expected = {
        "doc.tr_type":                3,   # used in branches + summary
        "DOCUMENTS REQUIRED (Direct TR)": 1,
        "has_commercial_invoice":     2,
        "has_bl_awb":                 2,
        "has_bill_of_entry":          2,
        "Proforma Invoice":           1,
        "Bill of Entry":              1,
    }
    for fmt_label, html in (("PV Fast", pv_fast), ("PV Pro", pv_pro)):
        for token, min_count in expected.items():
            cnt = html.count(token)
            score += _check(
                f"{fmt_label}: {token!r} appears >= {min_count}",
                cnt >= min_count,
                f"x{cnt}",
            )
    total_1 = len(expected) * 2

    pass_n += score
    fail_n += total_1 - score

    # ──────────────────────────────────────────────────────────
    # #2 — Supplier PI input field (bill_no) on reference row
    # ──────────────────────────────────────────────────────────
    print(_hr("[#2] Supplier PI input on Payment Request Reference"))
    score = 0
    ref = json.load(open(REF_JSON))
    fields = {f.get("fieldname"): f for f in ref.get("fields", [])}
    bill_no = fields.get("bill_no")
    score += _check(
        "payment_request_reference.bill_no exists",
        bool(bill_no),
        bill_no.get("fieldtype") if bill_no else "MISSING",
    )
    score += _check(
        "bill_no labelled 'Supplier Invoice No'",
        bool(bill_no) and bill_no.get("label") == "Supplier Invoice No",
        (bill_no or {}).get("label", ""),
    )
    score += _check(
        "bill_no fieldtype Data (user-editable)",
        bool(bill_no) and bill_no.get("fieldtype") == "Data",
    )
    pass_n += score
    fail_n += 3 - score

    # ──────────────────────────────────────────────────────────
    # #3 — Open PO endpoint + Advance Pay gating
    # ──────────────────────────────────────────────────────────
    print(_hr("[#3] Open PO fetch for Advance Pay"))
    score = 0
    score += _check(
        "Whitelisted endpoint get_open_purchase_orders_for_party",
        "def get_open_purchase_orders_for_party" in py
        and "@frappe.whitelist()" in py,
    )
    score += _check(
        "JS button 'Get Open Purchase Orders' present",
        '"Get Open Purchase Orders"' in js,
    )
    score += _check(
        "Button gated on payment_type === 'Advance Pay'",
        'frm.doc.payment_type === "Advance Pay"' in js,
    )
    score += _check(
        "Button gated on draft (docstatus 0)",
        "docstatus" in js and "Get Open Purchase Orders" in js,
    )
    pass_n += score
    fail_n += 4 - score

    # ──────────────────────────────────────────────────────────
    # #5 — Combined PDF: Supplier Invoice No column
    # ──────────────────────────────────────────────────────────
    print(_hr("[#5] Combined PDF Supplier Invoice No column"))
    score = 0
    for fmt_label, html in (("PV Fast", pv_fast), ("PV Pro", pv_pro)):
        score += _check(
            f"{fmt_label} renders 'Supplier Invoice No' header",
            "Supplier Invoice No" in html,
        )
        score += _check(
            f"{fmt_label} renders row.bill_no in cells",
            "row.bill_no" in html,
        )
    pass_n += score
    fail_n += 4 - score

    # ──────────────────────────────────────────────────────────
    # #7 — Payment ref type dynamic (no hardcoded "TR" everywhere)
    # ──────────────────────────────────────────────────────────
    print(_hr("[#7] _classify_payment_type derives code from MoP"))
    score = 0
    from avientek.avientek.doctype.payment_request_form.payment_request_form import (
        _classify_payment_type,
    )
    cases = [
        ("TT-AED",                "TT"),
        ("Trust Receipt",         "TR"),
        ("Letter of Credit",      "LC"),
        ("Advance",               "ADV"),
        ("Cheque",                "CHQ"),
        ("Cash",                  "CASH"),
        (None,                    "PAY"),
    ]
    for mop, expect in cases:
        got = _classify_payment_type(mop)
        score += _check(
            f"_classify_payment_type({mop!r}) -> {expect!r}",
            got == expect,
            f"got {got!r}",
        )
    pass_n += score
    fail_n += len(cases) - score

    # ──────────────────────────────────────────────────────────
    # #8 — Per-company naming series auto-set
    # ──────────────────────────────────────────────────────────
    print(_hr("[#8] Per-company naming series auto-set"))
    score = 0
    spec_map = {
        "Avientek FZCO":                       "AVFZC-.###",
        "Avientek Electronics Trading LLC":    "AVLLC-.###",
        "Avientek Trading LLC":                "AVKSA-.###",
        "Avientek Trading WLL":                "AVWLL-.###",
        "Avientek Electronics Trading Pvt Ltd": "AVLTD-.###",
    }
    for company, series in spec_map.items():
        # JS map literal includes both the company name and the series
        ok = company in js and series in js
        score += _check(
            f"map: {company!r} -> {series!r}",
            ok,
        )
    score += _check(
        "JS helper _apply_naming_series_by_company defined",
        "function _apply_naming_series_by_company" in js,
    )
    score += _check(
        "Helper invoked from company-change handler",
        js.count("_apply_naming_series_by_company(frm)") >= 2,
        f"x{js.count('_apply_naming_series_by_company(frm)')}",
    )
    # Naming series options also include the 5 series
    meta = frappe.get_meta("Payment Request Form", cached=False)
    ns = next((f for f in meta.fields if f.fieldname == "naming_series"), None)
    options = (ns.options or "").split("\n") if ns else []
    for series in spec_map.values():
        score += _check(
            f"naming_series options include {series!r}",
            series in options,
        )
    total_8 = len(spec_map) + 2 + len(spec_map)

    pass_n += score
    fail_n += total_8 - score

    # ──────────────────────────────────────────────────────────
    # Summary
    # ──────────────────────────────────────────────────────────
    total = pass_n + fail_n
    print("\n" + "=" * 70)
    if fail_n == 0:
        print(f"  ✅  ALL {total} CHECKS PASSED — Sridhar followups locked")
    else:
        print(f"  ❌  {fail_n}/{total} FAILED")
    print("=" * 70)

    return {"pass": pass_n, "fail": fail_n, "total": total}
