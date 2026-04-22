"""Rewrite the supplier_bank / supplier_swift inline Jinja block in the
"Payment Voucher Professional" print format so it uses the same fallback
chain as get_payment_voucher_context (which the Fast format already uses).

Row 26 of Jithin's spreadsheet (Apr 22): SWIFT code was not appearing on
the printed Payment Voucher. Root cause: Professional format's Jinja
only read Bank Account with is_default=1 and Bank.swift_number. If that
chain was blank (SWIFT stored in Bank Account.branch_code, or no
is_default row, or Employee party without a Bank Account record), the
SWIFT field printed empty.

Rather than duplicate the fallback logic inline in Jinja (fragile; Jinja
scoping rules around reassignment inside {% if %} are painful), we just
delegate to the server helper which already has the full chain:

  1. doc.supplier_bank_account
  2. is_default Bank Account for party
  3. any Bank Account for party
  4. Employee.bank_name / bank_ac_no / iban fallback
  5. SWIFT from Bank.swift_number → falls back to Bank Account.branch_code

Idempotent — skips if the format already calls get_payment_voucher_context.
"""

import re

import frappe


_PF_NAME = "Payment Voucher Professional"
_OLD_BLOCK_RE = re.compile(
    r"\{% set supplier_bank = \{\} %\}\s*"
    r"\{% set supplier_swift = \"\" %\}\s*"
    r"\{% if not is_internal_transfer and doc\.party and doc\.party_type %\}.*?"
    r"\{% endif %\}",
    re.DOTALL,
)

_NEW_BLOCK = (
    '{% set _ctx = frappe.call("avientek.avientek.doctype.payment_request_form.payment_request_form.get_payment_voucher_context", docname=doc.name) %}\n'
    '{% set supplier_bank = _ctx.supplier_bank or {} %}\n'
    '{% set supplier_swift = _ctx.supplier_swift or "" %}'
)


def execute():
    if not frappe.db.exists("Print Format", _PF_NAME):
        print(f"[fix_prf_professional_swift_fallback] {_PF_NAME} missing, skip")
        return

    html = frappe.db.get_value("Print Format", _PF_NAME, "html") or ""
    if not html:
        print("[fix_prf_professional_swift_fallback] empty html, skip")
        return

    if "get_payment_voucher_context" in html:
        print("[fix_prf_professional_swift_fallback] already rewritten, skip")
        return

    if not _OLD_BLOCK_RE.search(html):
        print("[fix_prf_professional_swift_fallback] old block pattern not found, skip")
        return

    new_html = _OLD_BLOCK_RE.sub(_NEW_BLOCK, html, count=1)
    if new_html == html:
        print("[fix_prf_professional_swift_fallback] substitution failed, skip")
        return

    frappe.db.set_value("Print Format", _PF_NAME, "html", new_html, update_modified=False)
    frappe.db.commit()
    frappe.clear_cache(doctype="Print Format")
    print(f"[fix_prf_professional_swift_fallback] rewrote supplier_swift block in {_PF_NAME}")
