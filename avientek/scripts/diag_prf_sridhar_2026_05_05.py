"""Forensic for the 2026-05-05 PRF concern list (Sridhar's 12-item review).

Walks the latest submitted PRF on the site and verifies each shipped fix
actually does what we claimed. Skips items #2, #3-extension, #5, #9-Siby,
#12-rename which need separate code work.

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.diag_prf_sridhar_2026_05_05.run
"""
from __future__ import annotations

import frappe
from frappe.utils import flt


def _pick_recent_prf(payment_type=None):
    where = "docstatus = 1 AND IFNULL(party,'') <> ''"
    if payment_type:
        where += " AND payment_type = %s"
        args = (payment_type,)
    else:
        args = ()
    rows = frappe.db.sql(
        f"""SELECT name, company, party_type, party, payment_type,
                   currency, tr_type, posting_date
            FROM `tabPayment Request Form`
            WHERE {where}
            ORDER BY modified DESC LIMIT 1""",
        args, as_dict=True,
    )
    return rows[0] if rows else None


def run():
    print("=" * 70)
    print(f"PRF SRIDHAR 2026-05-05 REVIEW — DIAGNOSTIC")
    print(f"site: {frappe.local.site}")
    print("=" * 70)

    # ── Item #1 — TR docs dynamic per tr_type ──
    print("\n[#1] TR docs dynamic by tr_type")
    prf = _pick_recent_prf(payment_type="Pay")
    if not prf:
        print("  no submitted PRF with payment_type=Pay — skip render")
    else:
        print(f"  using {prf.name} (tr_type={prf.tr_type or '(none)'})")
        for fmt in ("Payment Voucher Fast", "Payment Voucher Professional"):
            try:
                html = frappe.get_print("Payment Request Form", prf.name,
                                        print_format=fmt)
            except Exception as e:
                print(f"    {fmt}: render FAILED: {e}")
                continue
            branches = {
                "Advance TR": "DOCUMENTS REQUIRED (Advance TR)" in html,
                "Sight TR":   "DOCUMENTS REQUIRED (Sight TR)" in html,
                "Open TR":    "DOCUMENTS REQUIRED (Open TR)" in html,
                "Available":  "DOCUMENTS AVAILABLE" in html,
            }
            present = sum(1 for v in branches.values() if v)
            print(f"    {fmt}: branches present = {present}/4 "
                  f"({[k for k, v in branches.items() if v]})")

    # ── Item #4 — Outstanding from JV/PI/CrN/DrN, cross-company ──
    print("\n[#4] Outstanding fetch — supplier balance helpers")
    if prf:
        try:
            from avientek.avientek.doctype.payment_request_form.payment_request_form import (
                get_party_balance_in_doc_currency,
                get_party_balance_with_jv_inclusion,
            )
            base = flt(get_party_balance_in_doc_currency(
                prf.company, prf.party_type, prf.party,
                prf.currency, prf.posting_date,
            ))
            jv = flt(get_party_balance_with_jv_inclusion(
                prf.company, prf.party_type, prf.party,
                prf.currency, prf.posting_date,
            ))
            print(f"  party={prf.party}  ccy={prf.currency}  company={prf.company}")
            print(f"    standard balance:        {base:>14,.2f}")
            print(f"    + loose-JV balance:      {jv:>14,.2f}")
            print(f"    delta from JVs:          {jv - base:>14,.2f}")
            # Cross-company exposure
            other_companies = frappe.db.sql(
                """SELECT DISTINCT company FROM `tabGL Entry`
                   WHERE party_type=%s AND party=%s AND is_cancelled=0
                     AND company <> %s""",
                (prf.party_type, prf.party, prf.company), as_dict=True,
            )
            if other_companies:
                print(f"    party also has GL in other companies: "
                      f"{[r.company for r in other_companies]}")
                print(f"    *** GAP: helper currently scopes to one "
                      f"company only — Sridhar wants cross-company sum ***")
            else:
                print(f"    no other-company exposure for this party")
        except Exception as e:
            print(f"  helper invocation FAILED: {e}")

    # ── Item #6 — Combined PDF: Supplier Invoice No (bill_no) ──
    print("\n[#6] Combined PDF — Supplier Invoice No header in PV")
    if prf:
        ok = {}
        for fmt in ("Payment Voucher Fast", "Payment Voucher Professional"):
            try:
                html = frappe.get_print("Payment Request Form", prf.name,
                                        print_format=fmt)
            except Exception:
                continue
            ok[fmt] = ("Supplier Invoice No" in html
                      and "Invoice No.</th>" not in html)
        for k, v in ok.items():
            print(f"  {k}: {'OK' if v else 'FAIL'}")

    # ── Item #10 — supplier_balance.options bound to currency ──
    print("\n[#10] supplier_balance options")
    meta = frappe.get_meta("Payment Request Form")
    fmap = {f.fieldname: f for f in meta.fields}
    sb = fmap.get("supplier_balance")
    if sb:
        print(f"  options={sb.options!r}  expected='currency' -> "
              f"{'OK' if sb.options == 'currency' else 'FAIL'}")

    # ── Item #11 — 'TR' label everywhere in payment history ──
    print("\n[#11] Payment-type code 'TR' hardcoded (Sridhar #11 NEW BUG)")
    print("  Current code at payment_request_form.py:1862 + 1939 hardcodes")
    print("  payment_type_code = 'TR' and only overrides for TT modes.")
    if prf and prf.party_type == "Supplier":
        try:
            from avientek.avientek.doctype.payment_request_form.payment_request_form import (
                get_supplier_payment_history,
            )
            hist = get_supplier_payment_history(prf.party,
                                                company=prf.company,
                                                limit=15)
            tr_count = sum(1 for r in hist if r.get("type") == "TR")
            tt_count = sum(1 for r in hist if r.get("type") == "TT")
            other_count = sum(1 for r in hist if r.get("type")
                              not in ("TR", "TT"))
            print(f"  history rows: {len(hist)}  TR={tr_count} "
                  f"TT={tt_count} other={other_count}")
            if hist:
                modes = {(r.get("type"), r.get("source")): 0 for r in hist}
                for r in hist:
                    modes[(r.get("type"), r.get("source"))] += 1
                for (t, src), n in modes.items():
                    print(f"    type={t} source={src}: {n}")
        except Exception as e:
            print(f"  fetch FAILED: {e}")

    # ── Item #12 — Naming series options vs Sridhar's spec ──
    print("\n[#12] Naming series per company — current vs spec")
    ns_field = fmap.get("naming_series")
    current_options = (ns_field.options or "").split("\n") if ns_field else []
    print(f"  current options:  {current_options}")
    spec = {
        "Avientek FZCO":                         "AVFZC-",
        "Avientek Electronics Trading LLC":      "AVLLC-",
        "Avientek Trading WLL":                  "AVWLL-",
        "Avientek Trading LLC":                  "AVKSA-",
        "Avientek Electronics Trading Pvt Ltd":  "AVLTD-",
    }
    print(f"  spec (Sridhar):")
    for co, prefix in spec.items():
        present = any(o.startswith(prefix) for o in current_options)
        print(f"    {co:42s} -> {prefix:8s}  "
              f"{'PRESENT' if present else 'MISSING'}")

    print("\n" + "=" * 70)
    print("DONE — see findings above")
    print("=" * 70)
