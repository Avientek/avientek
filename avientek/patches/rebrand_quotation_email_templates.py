"""One-time rebrand of the 4 Quotation Email Templates to match the
Avientek brand palette (black header + cyan accent #00aeef +
white body) — replaces the placeholder dark-green / gold scheme used
in the initial seed.

Only overwrites templates whose `response` still contains the original
seed's signature markers (the old `#1f4e3d` dark-green or `#d4b95e`
gold). If admin has already edited the wording / palette, those
markers won't be present and the patch skips that template — admin
edits are preserved.

Run automatically via patches.txt on next migrate.
"""

import frappe

from avientek.patches.seed_quotation_email_templates import _TEMPLATES


_OLD_PALETTE_MARKERS = ("#1f4e3d", "#d4b95e", "#fdfaf3")


def _is_unedited_seed(response_html):
    """True if response still looks like the original un-edited seed —
    contains at least one of the old palette colour markers and none
    of the new brand colours."""
    if not response_html:
        return False
    if "#00aeef" in response_html:
        return False  # already on the new brand
    return any(marker in response_html for marker in _OLD_PALETTE_MARKERS)


def execute():
    rewritten = 0
    preserved = 0
    missing = 0
    for tmpl in _TEMPLATES:
        if not frappe.db.exists("Email Template", tmpl["name"]):
            missing += 1
            continue
        current = frappe.db.get_value("Email Template", tmpl["name"], "response") or ""
        if not _is_unedited_seed(current):
            preserved += 1
            continue
        frappe.db.set_value(
            "Email Template", tmpl["name"], {
                "subject": tmpl["subject"],
                "response": tmpl["response"],
                "use_html": 1,
            }, update_modified=False,
        )
        rewritten += 1
    if rewritten:
        frappe.db.commit()
    print(
        f"[rebrand_quotation_email_templates] rewritten={rewritten} "
        f"preserved_admin_edits={preserved} missing={missing}"
    )
