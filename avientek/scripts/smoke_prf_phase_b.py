"""Smoke for Phase B fixes (Sridhar 2026-05-06):
   #2/#3 Payment References table now visible for Advance Pay
   #9 Siby Joy + Siby Thomas John signature blocks on PV Fast (already
      present in PV Professional; verified)

#5 PDFs not searchable is NOT covered here — diagnosis needs a real
sample PDF Sridhar tried to copy text from. See Phase B doc for the
checks to run when a sample is available.

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_prf_phase_b.run
"""
from __future__ import annotations

import frappe


def _hr(t):
    return "\n" + "─" * 70 + f"\n{t}\n" + "─" * 70


def run():
    print("=" * 70)
    print("PRF PHASE B SMOKE — Sridhar 2026-05-06 fixes")
    print(f"site: {frappe.local.site}")
    print("=" * 70)

    pass_n, fail_n = 0, 0

    # ── #2 + #3 — reference_section depends_on includes Advance Pay ──
    print(_hr("[#2/#3] Payment References visible for Advance Pay"))
    meta = frappe.get_meta("Payment Request Form", cached=False)
    fmap = {f.fieldname: f for f in meta.fields}
    rs = fmap.get("reference_section")
    if not rs:
        print("  FAIL  reference_section field missing")
        fail_n += 1
    else:
        depends = (rs.depends_on or "").strip()
        ok = "Advance Pay" in depends and "Pay" in depends
        flag = "OK  " if ok else "FAIL"
        print(f"  {flag}  reference_section.depends_on = {depends!r}")
        if ok:
            pass_n += 1
        else:
            fail_n += 1

    # Property setter present (for sites where DocField sync doesn't propagate)
    ps = frappe.db.exists(
        "Property Setter",
        "Payment Request Form-reference_section-depends_on",
    )
    flag = "OK  " if ps else "FAIL"
    print(f"  {flag}  Property Setter exists for "
          f"reference_section.depends_on")
    if ps:
        pass_n += 1
    else:
        fail_n += 1

    # ── #9 — Siby Joy + Siby Thomas John in both PV formats ──
    print(_hr("[#9] Siby signature blocks in PV print formats"))
    for fmt in ("Payment Voucher Fast", "Payment Voucher Professional"):
        if not frappe.db.exists("Print Format", fmt):
            print(f"  SKIP {fmt}: not found on this site")
            continue
        html = frappe.db.get_value("Print Format", fmt, "html") or ""
        joy_n = html.count("Siby Joy")
        john_n = html.count("Siby Thomas John")
        # PV Fast and Pro each have 3 sig branches
        ok = joy_n >= 3 and john_n >= 3
        flag = "OK  " if ok else "FAIL"
        print(f"  {flag}  {fmt}: Siby Joy x{joy_n}, "
              f"Siby Thomas John x{john_n} (need >=3 each)")
        if ok:
            pass_n += 1
        else:
            fail_n += 1

    # ── Render check on a sample PRF ──
    print(_hr("[Render] PV Fast + PV Professional on a sample PRF"))
    prf_row = frappe.db.sql(
        """SELECT name FROM `tabPayment Request Form`
           WHERE docstatus = 1 ORDER BY modified DESC LIMIT 1""",
        as_dict=True,
    )
    if not prf_row:
        print("  SKIP  no submitted PRF on this site")
    else:
        name = prf_row[0]["name"]
        for fmt in ("Payment Voucher Fast", "Payment Voucher Professional"):
            try:
                html = frappe.get_print(
                    "Payment Request Form", name, print_format=fmt,
                )
                joy_in = "Siby Joy" in html
                john_in = "Siby Thomas John" in html
                flag = "OK  " if joy_in and john_in else "FAIL"
                print(f"  {flag}  {fmt} ({name}): Siby Joy={joy_in}, "
                      f"Siby Thomas John={john_in}")
                if joy_in and john_in:
                    pass_n += 1
                else:
                    fail_n += 1
            except Exception as e:
                print(f"  FAIL  {fmt} render: {e}")
                fail_n += 1

    # ── Verdict ──
    print(_hr("Verdict"))
    print(f"  pass: {pass_n}    fail: {fail_n}")
    if fail_n == 0:
        print(f"\n  ✅ PASS — Phase B fixes verified (#2/#3 + #9)")
    else:
        print(f"\n  ❌ FAIL — {fail_n} check(s) failed")
    return {"pass": pass_n, "fail": fail_n}
