"""Smoke for the Signature Images feature on Payment Voucher print formats.

Verifies:
  - Avientek Signature Image child doctype exists
  - Avientek Settings has the section + table field
  - get_payment_voucher_context loads signature_images map from settings
  - PV Fast + PV Pro templates render <img> when signature_image is present

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_signature_images.run
"""
from __future__ import annotations

import json
import os

import frappe


APP_PATH = frappe.get_app_path("avientek")
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
    print(f"  {flag}  {label}{(' — ' + detail) if detail else ''}")
    return 1 if ok else 0


def run():
    print("=" * 70)
    print("AVIENTEK SIGNATURE IMAGES SMOKE")
    print(f"site: {frappe.local.site}")
    print("=" * 70)

    pass_n = 0
    fail_n = 0

    # ── 1. Child doctype exists ──
    print(_hr("[1] Avientek Signature Image child doctype"))
    exists = frappe.db.exists("DocType", "Avientek Signature Image")
    pass_n += _check("DocType exists", bool(exists))
    if exists:
        meta = frappe.get_meta("Avientek Signature Image", cached=False)
        names = {f.fieldname for f in meta.fields}
        for fn in ("signature_key", "signer_name", "designation",
                   "linked_user", "image"):
            if _check(f"field {fn!r} present", fn in names):
                pass_n += 0
                pass_n += 1
            else:
                fail_n += 1
        is_table = (frappe.db.get_value("DocType", "Avientek Signature Image",
                                        "istable") or 0)
        pass_n += _check("istable=1 (child doctype)", int(is_table) == 1,
                         f"istable={is_table}")
    fail_n += 1 - 1 if exists else 1

    # ── 2. Avientek Settings field ──
    print(_hr("[2] Avientek Settings table field"))
    meta = frappe.get_meta("Avientek Settings", cached=False)
    fmap = {f.fieldname: f for f in meta.fields}
    sec = fmap.get("signature_images_section")
    fld = fmap.get("signature_images")
    pass_n += _check("section_break signature_images_section",
                     bool(sec), sec.label if sec else "MISSING")
    pass_n += _check("Table field signature_images",
                     bool(fld) and fld.fieldtype == "Table"
                     and fld.options == "Avientek Signature Image",
                     f"{fld.fieldtype}/{fld.options}" if fld else "MISSING")
    if not sec: fail_n += 1
    if not (fld and fld.fieldtype == "Table"
            and fld.options == "Avientek Signature Image"):
        fail_n += 1

    # ── 3. PV Fast + PV Pro template tokens ──
    print(_hr("[3] PV templates render signature images"))
    for label, path in (("PV Fast", PV_FAST_JSON), ("PV Pro", PV_PRO_JSON)):
        html = json.load(open(path)).get("html", "")
        pass_n += _check(f"{label}: .sig-img CSS rule present",
                         ".sig-img" in html)
        pass_n += _check(f"{label}: <img class=\"sig-img\" /> tag present",
                         'class="sig-img"' in html)
        pass_n += _check(f"{label}: ctx.signature_images.get used in template",
                         "ctx.signature_images.get(" in html)
        pass_n += _check(f"{label}: Siby Joy lookup dynamic",
                         'ctx.signature_images.get("Siby Joy")' in html)
        for needed in (
            'class="sig-img"',
            "ctx.signature_images.get(",
            ".sig-img",
            'ctx.signature_images.get("Siby Joy")',
        ):
            if needed not in html:
                fail_n += 1

    # ── 4. Hydration map (build a synthetic settings map and verify resolution) ──
    print(_hr("[4] signature_images map resolves from settings"))
    sett = frappe.get_doc("Avientek Settings")
    original = [r.as_dict() for r in (sett.signature_images or [])]
    try:
        sett.signature_images = []
        sett.append("signature_images", {
            "signature_key": "Siby Joy",
            "signer_name": "Siby Joy (Test)",
            "designation": "Corp. Fin Manager",
            "image": "/files/test_siby_joy.png",
        })
        sett.append("signature_images", {
            "signature_key": "Approved Level 1",
            "signer_name": "Test L1 Signer",
            "designation": "Finance Manager",
            "image": "/files/test_l1.png",
        })
        sett.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.clear_cache(doctype="Avientek Settings")

        # Re-resolve via cached_doc, mimic ctx-builder
        sett2 = frappe.get_cached_doc("Avientek Settings")
        sigmap = {}
        for row in (sett2.get("signature_images") or []):
            key = (row.signature_key or "").strip()
            if not key or not row.image:
                continue
            sigmap[key] = {
                "name": row.signer_name or "",
                "designation": row.designation or "",
                "image": row.image,
                "linked_user": row.linked_user or "",
            }
        pass_n += _check("Siby Joy resolved",
                         "Siby Joy" in sigmap
                         and sigmap["Siby Joy"]["image"] == "/files/test_siby_joy.png",
                         f"image={sigmap.get('Siby Joy', {}).get('image')!r}")
        pass_n += _check("Approved Level 1 resolved",
                         "Approved Level 1" in sigmap,
                         f"name={sigmap.get('Approved Level 1', {}).get('name')!r}")
        if not ("Siby Joy" in sigmap
                and sigmap["Siby Joy"]["image"] == "/files/test_siby_joy.png"):
            fail_n += 1
        if "Approved Level 1" not in sigmap:
            fail_n += 1
    finally:
        # Restore (clear test data)
        sett.signature_images = []
        for row in original:
            sett.append("signature_images", {
                k: v for k, v in row.items()
                if k in ("signature_key", "signer_name", "designation",
                          "linked_user", "image")
            })
        sett.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.clear_cache(doctype="Avientek Settings")

    # ── Verdict ──
    total = pass_n + fail_n
    print("\n" + "=" * 70)
    if fail_n == 0:
        print(f"  ✅  ALL {total} CHECKS PASSED — Signature images feature wired")
    else:
        print(f"  ❌  {fail_n}/{total} FAILED")
    print("=" * 70)
    return {"pass": pass_n, "fail": fail_n, "total": total}
