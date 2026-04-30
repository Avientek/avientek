"""Avientek custom print formats insert the Letter Head's content via
`{{letter_head.content}}`. That just spits out the raw HTML string —
any Jinja inside the letter head (e.g. AVN - India / AVN - Singapore
conditionally render "TAX INVOICE" / "Tax Credit Note" / doc.doctype)
appears as literal source text in the printed PDF.

Reported 2026-04-27 by Sridhar (screenshot of PINV-LTD-25-00391's
Combined PDF showing the Jinja conditional as plain text in the
Purchase Order header column).

Fix: rewrite each affected print format to use
    {{ frappe.render_template(letter_head.content, {"doc": doc, "letter_head": letter_head}) }}
so embedded Jinja inside the letter head is evaluated against the
current doc.

Scope:
  - All custom_format=1 / disabled=0 Print Formats whose html contains
    the literal `letter_head.content` token.
  - Idempotent: skips rows already using `frappe.render_template`.

Affected formats observed at patch time:
  Avientek DN, Avientek Payment, Avientek PI, Avientek PI Format,
  Avientek PO, Avientek PR, Avientek Quotation, Avientek SI,
  Avientek SI 2026, Avientek SI CN, Avientek SI New, Avientek SI Old,
  Avientek SO, Avientek SO 2026, KSA DN, KSA Print 2, Sample,
  Stock Entry Format, Test delivery note.
"""

import re

import frappe


_OLD = re.compile(r"\{\{\s*letter_head\.content\s*\}\}")
_NEW = (
    "{{ frappe.render_template(letter_head.content, "
    "{\"doc\": doc, \"letter_head\": letter_head}) }}"
)
_ALREADY_FIXED_TOKEN = "frappe.render_template(letter_head.content"


def execute():
    rows = frappe.db.sql(
        """SELECT name, html FROM `tabPrint Format`
           WHERE html LIKE %s
             AND custom_format = 1
             AND IFNULL(disabled, 0) = 0""",
        ("%letter_head.content%",),
        as_dict=True,
    )

    fixed = 0
    skipped_already_fixed = 0
    skipped_no_match = 0
    failed = 0

    for r in rows:
        html = r.html or ""
        if _ALREADY_FIXED_TOKEN in html and not _OLD.search(html):
            skipped_already_fixed += 1
            continue
        new_html, n = _OLD.subn(_NEW, html)
        if n == 0:
            # `letter_head.content` appears but not as `{{letter_head.content}}`
            # (e.g. inside a comment) — leave alone.
            skipped_no_match += 1
            continue
        try:
            frappe.db.set_value(
                "Print Format", r.name, "html", new_html, update_modified=False,
            )
            fixed += 1
            print(f"[render_letter_head_content_as_jinja] patched {r.name!r} ({n} replacement{'s' if n > 1 else ''})")
        except Exception:
            failed += 1
            frappe.log_error(
                title=f"render_letter_head_content_as_jinja failed for {r.name}",
                message=frappe.get_traceback(),
            )

    if fixed:
        frappe.db.commit()
        try:
            frappe.clear_cache(doctype="Print Format")
        except Exception:
            pass

    print(
        f"[render_letter_head_content_as_jinja] fixed={fixed} "
        f"already_fixed={skipped_already_fixed} no_match={skipped_no_match} "
        f"failed={failed}"
    )
