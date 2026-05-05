"""Smoke test for Phase A fixes (Sridhar 2026-05-05 PRF review):
   #11 TR label dynamic, #12 naming series rename, #4 cross-company balance.

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_prf_phase_a.run
"""
from __future__ import annotations

import frappe
from frappe.utils import flt


def _hr(t):
    return "\n" + "─" * 70 + f"\n{t}\n" + "─" * 70


def run():
    print("=" * 70)
    print("PRF PHASE A SMOKE — Sridhar 2026-05-05 fixes")
    print(f"site: {frappe.local.site}")
    print("=" * 70)

    pass_count = 0
    fail_count = 0

    # ── #11 — TR everywhere → dynamic _classify_payment_type ──
    print(_hr("[#11] _classify_payment_type derives code from MoP"))
    from avientek.avientek.doctype.payment_request_form.payment_request_form import (
        _classify_payment_type,
    )
    cases = [
        ("TT-AED",                   "TT"),
        ("Telegraphic Transfer",     "TT"),
        ("SWIFT",                    "TT"),
        ("Trust Receipt",            "TR"),
        ("TR-USD",                   "TR"),
        ("Letter of Credit",         "LC"),
        ("LC-AED",                   "LC"),
        ("Advance",                  "ADV"),
        ("Cheque",                   "CHQ"),
        ("Cash",                     "CASH"),
        ("Online Banking",           "ONL"),
        ("Visa Card",                "CARD"),
        ("NEFT",                     "BT"),
        ("Demand Draft",             "DD"),
        ("",                         "PAY"),
        (None,                       "PAY"),
        ("Some Weird Mode",          "SOME"),
    ]
    for inp, expected in cases:
        got = _classify_payment_type(inp)
        ok = got == expected
        flag = "OK" if ok else "FAIL"
        print(f"  {flag}  _classify_payment_type({inp!r:32s}) = {got!r:8s}  expected {expected!r}")
        if ok:
            pass_count += 1
        else:
            fail_count += 1

    # ── #12 — Naming series options match Sridhar's spec ──
    print(_hr("[#12] PRF naming_series options"))
    meta = frappe.get_meta("Payment Request Form", cached=False)
    fmap = {f.fieldname: f for f in meta.fields}
    ns = fmap.get("naming_series")
    options = (ns.options or "").split("\n") if ns else []
    spec = ["AVFZC-.###", "AVLLC-.###", "AVKSA-.###",
            "AVWLL-.###", "AVLTD-.###"]
    for s in spec:
        present = s in options
        flag = "OK" if present else "FAIL"
        print(f"  {flag}  series option {s!r}")
        if present:
            pass_count += 1
        else:
            fail_count += 1
    legacy = ["AVETLL-.###", "AVTLL-.###", "AVTWL-.###", "AVETPL-.###"]
    for s in legacy:
        if s in options:
            print(f"  WARN  legacy option still present (won't break, "
                  f"existing names still valid): {s!r}")

    # ── #4 — Cross-company outstanding helper callable ──
    print(_hr("[#4] get_party_balance_cross_company callable"))
    from avientek.avientek.doctype.payment_request_form.payment_request_form import (
        get_party_balance_cross_company,
        get_party_balance_with_jv_inclusion,
        get_party_balance_in_doc_currency,
    )
    # Pick a supplier with cross-company GL footprint to actually test.
    cross = frappe.db.sql(
        """SELECT party, COUNT(DISTINCT company) AS n_companies
           FROM `tabGL Entry`
           WHERE party_type='Supplier' AND is_cancelled=0
             AND IFNULL(party,'') <> ''
           GROUP BY party
           HAVING n_companies >= 2
           ORDER BY n_companies DESC LIMIT 1""", as_dict=True,
    )
    if not cross:
        print("  no cross-company supplier found; using single-company case")
        sup_row = frappe.db.sql(
            """SELECT party, company FROM `tabGL Entry`
               WHERE party_type='Supplier' AND is_cancelled=0
               ORDER BY posting_date DESC LIMIT 1""", as_dict=True,
        )
        if not sup_row:
            print("  FAIL  no GL entries for Supplier on this site")
            fail_count += 1
        else:
            sup = sup_row[0]["party"]
            co = sup_row[0]["company"]
            ccy = frappe.get_cached_value("Company", co, "default_currency")
            single = flt(get_party_balance_with_jv_inclusion(co, "Supplier", sup, ccy))
            cross_v = flt(get_party_balance_cross_company(co, "Supplier", sup, ccy))
            print(f"  supplier={sup}  company={co}  ccy={ccy}")
            print(f"    single-company balance: {single:>14,.2f}")
            print(f"    cross-company balance:  {cross_v:>14,.2f}")
            if abs(cross_v) > 0:
                print(f"  OK    helper returned non-zero")
                pass_count += 1
            else:
                print(f"  WARN  helper returned 0 — verify supplier has open GL")
    else:
        sup = cross[0]["party"]
        n = cross[0]["n_companies"]
        # Pick the originating company with most GL volume
        co_row = frappe.db.sql(
            """SELECT company, COUNT(*) AS n FROM `tabGL Entry`
               WHERE party_type='Supplier' AND party=%s AND is_cancelled=0
               GROUP BY company ORDER BY n DESC LIMIT 1""",
            (sup,), as_dict=True,
        )
        co = co_row[0]["company"]
        ccy = frappe.get_cached_value("Company", co, "default_currency")
        base = flt(get_party_balance_in_doc_currency(co, "Supplier", sup, ccy))
        single = flt(get_party_balance_with_jv_inclusion(co, "Supplier", sup, ccy))
        cross_v = flt(get_party_balance_cross_company(co, "Supplier", sup, ccy))
        print(f"  supplier={sup}  spans {n} companies, originating={co}, ccy={ccy}")
        print(f"    standard balance (1 co):       {base:>14,.2f}")
        print(f"    + loose-JV (1 co):             {single:>14,.2f}")
        print(f"    cross-company total:           {cross_v:>14,.2f}")
        # Cross-company should be ≥ single-company in absolute magnitude
        if abs(cross_v) >= abs(single) - 0.01:
            print(f"  OK    cross-company >= single-company in magnitude")
            pass_count += 1
        else:
            print(f"  FAIL  cross-company should aggregate more, not less")
            fail_count += 1

    # ── Verdict ──
    print(_hr("Verdict"))
    print(f"  pass: {pass_count}    fail: {fail_count}")
    print()
    if fail_count == 0:
        print("  PASS — Phase A fixes verified")
    else:
        print(f"  FAIL — {fail_count} check(s) failed")
    return {"pass": pass_count, "fail": fail_count}
