"""Force-sync the Payment Voucher Professional + Fast print formats from
their on-disk JSON sources to the DB.

Reason: bench migrate does NOT re-import print formats whose existing DB
row has custom_format=1; the row keeps whatever the last manual patch
wrote. We've now made source-controlled changes to the items table
(Supplier Invoice No, Reference + Remarks split) per Sridhar 2026-04-27
items #7 + #8, so we need a one-off patch to push the new html into
the DB. Idempotent — checks for the new header marker first.
"""

import json
import os

import frappe


_FORMATS = {
    "Payment Voucher Professional":
        os.path.join(
            "avientek", "print_format",
            "payment_voucher_professional",
            "payment_voucher_professional.json",
        ),
    "Payment Voucher Fast":
        os.path.join(
            "avientek", "print_format",
            "payment_voucher_fast",
            "payment_voucher_fast.json",
        ),
}

_NEW_HEADER_MARKER = "Supplier Invoice No"


def execute():
    # frappe.get_app_path("avientek") = .../apps/avientek/avientek (the
    # module directory), and the print_format folders sit *inside* it as
    # avientek/print_format/...; so we use app_path as the base directly.
    base = frappe.get_app_path("avientek")

    fixed = 0
    skipped_already = 0
    skipped_missing = 0

    for pf_name, rel in _FORMATS.items():
        if not frappe.db.exists("Print Format", pf_name):
            print(f"[sync_pv_formats] {pf_name!r} not in DB — skip")
            skipped_missing += 1
            continue

        path = os.path.join(base, rel)
        if not os.path.exists(path):
            print(f"[sync_pv_formats] source missing: {path}")
            skipped_missing += 1
            continue

        try:
            data = json.load(open(path))
        except Exception:
            frappe.log_error(
                title=f"sync_pv_formats: failed to read {path}",
                message=frappe.get_traceback(),
            )
            continue

        new_html = data.get("html") or ""
        if not new_html:
            print(f"[sync_pv_formats] {pf_name!r}: source has empty html — skip")
            continue

        existing_html = frappe.db.get_value("Print Format", pf_name, "html") or ""
        if (_NEW_HEADER_MARKER in existing_html) and (existing_html == new_html):
            skipped_already += 1
            continue

        frappe.db.set_value(
            "Print Format", pf_name, "html", new_html, update_modified=False,
        )
        fixed += 1
        print(f"[sync_pv_formats] {pf_name!r}: html refreshed from source")

    if fixed:
        frappe.db.commit()
        try:
            frappe.clear_cache(doctype="Print Format")
        except Exception:
            pass

    print(
        f"[sync_pv_formats] fixed={fixed} already_in_sync={skipped_already} "
        f"missing={skipped_missing}"
    )
