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

        # ── Page-layout attrs (Sammish 2026-06-20, AVFZC-02239 Brand
        # Summary PDF crop): the syncer used to push only `html`, so
        # any edit to layout-affecting fields in the source JSON would
        # silently never reach prod. Now sync those too — gated by
        # None so a missing key in source JSON doesn't wipe the
        # existing DB value.
        #
        # NB: Print Format doctype does NOT have `orientation` or
        # `page_size` columns (Frappe stores those in Print Settings
        # globally, not per-format). For per-format orientation, use
        # CSS `@page { size: A4 landscape; }` in the `css` field —
        # wkhtmltopdf respects it. Both JSON files now ship that rule
        # via `css` for the Brand Summary section's 17 columns.
        LAYOUT_FIELDS = ("css", "font_size",
                         "margin_top", "margin_bottom",
                         "margin_left", "margin_right")
        layout_changes = {}
        for fld in LAYOUT_FIELDS:
            src_val = data.get(fld)
            if src_val is None:
                continue
            cur_val = frappe.db.get_value("Print Format", pf_name, fld)
            if cur_val != src_val:
                layout_changes[fld] = src_val

        existing_html = frappe.db.get_value("Print Format", pf_name, "html") or ""
        html_in_sync = (_NEW_HEADER_MARKER in existing_html) and (existing_html == new_html)
        if html_in_sync and not layout_changes:
            skipped_already += 1
            continue

        if not html_in_sync:
            frappe.db.set_value(
                "Print Format", pf_name, "html", new_html, update_modified=False,
            )
            print(f"[sync_pv_formats] {pf_name!r}: html refreshed from source")

        for fld, val in layout_changes.items():
            frappe.db.set_value(
                "Print Format", pf_name, fld, val, update_modified=False,
            )
            print(f"[sync_pv_formats] {pf_name!r}: {fld} → {val!r}")

        fixed += 1

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
