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

_OLD_CALL_RE = re.compile(
    r'\{%\s*set\s+ctx\s*=\s*frappe\.call\(\s*'
    r'"avientek\.avientek\.doctype\.payment_request_form\.payment_request_form\.get_payment_voucher_context"\s*,\s*'
    r'docname\s*=\s*doc\.name\s*\)\s*%\}'
)

_NEW_CALL = (
    '{% set _get_ctx = frappe.get_attr("avientek.avientek.doctype.payment_request_form.payment_request_form.get_payment_voucher_context") %}\n'
    '{% set ctx = _get_ctx(doc.name) %}'
)


def execute():
    if not frappe.db.exists("Print Format", _PF_NAME):
        print(f"[fix_prf_fast_frappe_call_worker] {_PF_NAME} missing, skip")
        return

    html = frappe.db.get_value("Print Format", _PF_NAME, "html") or ""
    if not html:
        print("[fix_prf_fast_frappe_call_worker] empty html, skip")
        return

    if "frappe.get_attr" in html and "get_payment_voucher_context" in html:
        print("[fix_prf_fast_frappe_call_worker] already rewritten, skip")
        return

    if not _OLD_CALL_RE.search(html):
        print("[fix_prf_fast_frappe_call_worker] old frappe.call pattern not found, skip")
        return

    new_html = _OLD_CALL_RE.sub(_NEW_CALL, html, count=1)
    if new_html == html:
        print("[fix_prf_fast_frappe_call_worker] substitution failed, skip")
        return

    frappe.db.set_value("Print Format", _PF_NAME, "html", new_html, update_modified=False)
    frappe.db.commit()
    frappe.clear_cache(doctype="Print Format")
    print(f"[fix_prf_fast_frappe_call_worker] swapped frappe.call for frappe.get_attr in {_PF_NAME}")
