"""Rewrite "Payment Voucher Fast" print format so it resolves its server-side
context via frappe.get_attr instead of frappe.call.

Reported 2026-04-22 by Shijin on qcs-avntk-test (PRF AVFZC-021): after
the combined-PDF worker fix, the download returned:

    Error in print format on line 2: request

Line 2 of the Fast format is:
    {% set ctx = frappe.call("avientek.avientek...get_payment_voucher_context",
                             docname=doc.name) %}

frappe.call in Jinja dispatches through the HTTP whitelist handler, which
touches frappe.local.request. In a background worker there is no request
object, so the Jinja expression raises a KeyError/AttributeError on
"request" and the whole render aborts — which is why the download came
back blank in the first place and now surfaces as a clear error.

Fix: use frappe.get_attr to resolve the function path and call it
directly. Pure Python call, no HTTP plumbing, works in any context.

Idempotent — skips if the template already uses frappe.get_attr.
"""

import re

import frappe


_PF_NAME = "Payment Voucher Fast"

_OLD_PATTERNS = [
    # original frappe.call (HTTP whitelist path — fails in background workers)
    re.compile(
        r'frappe\.call\(\s*"avientek\.avientek\.doctype\.payment_request_form'
        r'\.payment_request_form\.get_payment_voucher_context"\s*,\s*docname\s*=\s*doc\.name\s*\)'
    ),
    # interim frappe.get_attr attempt (not in Jinja safe globals — also fails)
    re.compile(
        r'frappe\.get_attr\(\s*"avientek\.avientek\.doctype\.payment_request_form'
        r'\.payment_request_form\.get_payment_voucher_context"\s*\)\s*\(\s*doc\.name\s*\)'
    ),
]

_NEW_CALL = "get_payment_voucher_context(doc.name)"


def execute():
    if not frappe.db.exists("Print Format", _PF_NAME):
        print(f"[fix_prf_fast_frappe_call_worker] {_PF_NAME} missing, skip")
        return

    html = frappe.db.get_value("Print Format", _PF_NAME, "html") or ""
    if not html:
        print("[fix_prf_fast_frappe_call_worker] empty html, skip")
        return

    if "get_payment_voucher_context(doc.name)" in html:
        print("[fix_prf_fast_frappe_call_worker] already using direct Jinja call, skip")
        return

    new_html = html
    replaced = False
    for pattern in _OLD_PATTERNS:
        candidate = pattern.sub(_NEW_CALL, new_html, count=1)
        if candidate != new_html:
            new_html = candidate
            replaced = True
            break

    if not replaced:
        print("[fix_prf_fast_frappe_call_worker] no matching pattern found, skip")
        return

    frappe.db.set_value("Print Format", _PF_NAME, "html", new_html, update_modified=False)
    frappe.db.commit()
    frappe.clear_cache(doctype="Print Format")
    print(f"[fix_prf_fast_frappe_call_worker] rewrote {_PF_NAME} to use direct Jinja function call")
