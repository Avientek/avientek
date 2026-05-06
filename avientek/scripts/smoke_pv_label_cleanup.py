"""Smoke for Sridhar 2026-05-06 jithin commends:
  #6 Acknowledged-By -> Approved
  #7 strip "By"/"-By" suffix from sig labels
  Verifies BOTH the on-disk JSON source AND a rendered PRF print HTML.
"""
import json
import frappe


def run():
    print("=" * 70)
    print("PV LABEL CLEANUP SMOKE")
    print(f"site: {frappe.local.site}")
    print("=" * 70)
    pass_n, fail_n = 0, 0

    # ── 1. Source JSON ──
    for path in (
        "avientek/avientek/print_format/payment_voucher_fast/"
        "payment_voucher_fast.json",
        "avientek/avientek/print_format/payment_voucher_professional/"
        "payment_voucher_professional.json",
    ):
        full = frappe.get_app_path("avientek", "..", path)
        h = json.load(open(full))["html"]
        forbidden = ["Prepared By", "Authorised-By", "Approved-By",
                     "Approve Level", "Acknowledged-By"]
        bad = {k: h.count(k) for k in forbidden if h.count(k) > 0}
        flag = "OK" if not bad else "FAIL"
        print(f"  {flag}  source {path.split('/')[-1]}: forbidden={bad or 'none'}")
        if not bad:
            pass_n += 1
        else:
            fail_n += 1

    # ── 2. Rendered HTML on a real PRF (Pay type) ──
    prf = frappe.db.sql(
        """SELECT name FROM `tabPayment Request Form`
           WHERE docstatus=1 AND payment_type='Pay'
           ORDER BY modified DESC LIMIT 1""", as_dict=True,
    )
    if not prf:
        print("  no submitted Pay-type PRF — skip render check")
    else:
        name = prf[0]["name"]
        for fmt in ("Payment Voucher Fast", "Payment Voucher Professional"):
            try:
                html = frappe.get_print(
                    "Payment Request Form", name, print_format=fmt,
                )
            except Exception as e:
                print(f"  ✗ {fmt} render failed: {e}")
                fail_n += 1
                continue
            forbidden = ["Prepared By", "Authorised-By", "Approved-By",
                         "Approve Level", "Acknowledged-By"]
            bad = {k: html.count(k) for k in forbidden if html.count(k) > 0}
            siby_joy = html.count("Siby Joy")
            siby_thomas = html.count("Siby Thomas John")
            ok = (not bad) and siby_joy and siby_thomas
            flag = "OK" if ok else "FAIL"
            print(f"  {flag}  rendered {fmt} ({name}): "
                  f"forbidden={bad or 'none'}  Siby Joy={siby_joy}  "
                  f"Siby Thomas={siby_thomas}")
            if ok:
                pass_n += 1
            else:
                fail_n += 1

    print()
    print(f"  pass: {pass_n}    fail: {fail_n}")
    if fail_n == 0 and pass_n > 0:
        print("  ✅ PASS")
    else:
        print("  ❌ FAIL")
    return {"pass": pass_n, "fail": fail_n}
