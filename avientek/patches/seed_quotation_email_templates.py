"""Seed 4 professional Email Templates for the Quotation approval flow.

Created once if missing — never overwrites existing rows so admins can
edit the wording in /app/email-template without losing changes on next
migrate.

Used by `avientek.api.quotation_high_probability._render_quotation_email`
(prob-100 alert) and the upcoming workflow-state notification hook
(approval-request / approved / rejected).
"""

import frappe


# Avientek brand palette — taken from avientek.com (Jithin 2026-05-18):
# black header background, bright cyan-blue accent (the logo colour),
# white card body. Matches the site's hero strip exactly.
_BRAND_HEADER = (
    '<table width="100%" cellpadding="0" cellspacing="0" '
    'style="background:#000000;color:#ffffff;'
    'font-family:Segoe UI,Arial,sans-serif;">'
    '<tr><td style="padding:18px 24px;font-size:20px;font-weight:700;'
    'letter-spacing:1px;color:#00aeef;">AVIENTEK</td>'
    '<td align="right" style="padding:18px 24px;font-size:11px;'
    'color:#cccccc;letter-spacing:0.3px;">{{ doc.doctype }} {{ doc.name }}</td></tr></table>'
)

_DETAIL_TABLE = (
    '<table width="100%" cellpadding="0" cellspacing="0" '
    'style="border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;'
    'font-size:13px;margin-top:18px;">'
    '<tr><td style="padding:6px 0;color:#666;width:38%;">Customer</td>'
    '<td style="padding:6px 0;font-weight:500;color:#111;">'
    '{{ doc.party_name or doc.quotation_to or "—" }}</td></tr>'
    '<tr><td style="padding:6px 0;color:#666;">Salesperson</td>'
    '<td style="padding:6px 0;color:#111;">{{ doc.owner }}</td></tr>'
    '<tr><td style="padding:6px 0;color:#666;">Grand Total</td>'
    '<td style="padding:6px 0;font-weight:700;color:#00aeef;">'
    '{{ "{:,.2f}".format(doc.grand_total or 0) }} {{ doc.currency or "" }}</td></tr>'
    '<tr><td style="padding:6px 0;color:#666;">Probability</td>'
    '<td style="padding:6px 0;color:#111;">{{ doc.probability or 0 }}%</td></tr>'
    '<tr><td style="padding:6px 0;color:#666;">Valid Till</td>'
    '<td style="padding:6px 0;color:#111;">{{ doc.valid_till or "—" }}</td></tr>'
    '</table>'
)

_BUTTON = (
    '<p style="margin-top:26px;">'
    '<a href="{{ frappe.utils.get_url() }}/app/quotation/{{ doc.name }}" '
    'style="display:inline-block;padding:11px 24px;background:#00aeef;'
    'color:#ffffff;text-decoration:none;font-weight:600;'
    'font-family:Segoe UI,Arial,sans-serif;font-size:13px;'
    'border-radius:3px;letter-spacing:0.3px;">Open Quotation →</a></p>'
)

_FOOTER = (
    '<p style="margin-top:32px;font-size:11px;color:#999;'
    'font-family:Segoe UI,Arial,sans-serif;border-top:1px solid #eee;'
    'padding-top:14px;">'
    'This is an automated notification from Avientek ERP. To turn these '
    'emails off, edit <b>Avientek Settings → Notifications</b>.</p>'
)


def _body(intro_html):
    return (
        '<div style="max-width:640px;margin:0 auto;background:#ffffff;'
        'padding:0 0 24px 0;border:1px solid #ececec;">'
        + _BRAND_HEADER
        + '<div style="padding:26px;color:#222;">'
        + intro_html
        + _DETAIL_TABLE
        + _BUTTON
        + _FOOTER
        + '</div></div>'
    )


_TEMPLATES = [
    {
        "name": "Quotation Approval Required",
        "subject": "Approval Needed: Quotation {{ doc.name }} — {{ doc.party_name }}",
        "response": _body(
            '<p style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;">'
            'A quotation requires your approval. Please review the details below '
            'and approve or send back for revision.</p>'
        ),
    },
    {
        "name": "Quotation Approved",
        "subject": "Approved: Quotation {{ doc.name }} — {{ doc.party_name }}",
        "response": _body(
            '<p style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;">'
            'Your quotation has been <b style="color:#00aeef;">approved</b> and is '
            'ready to share with the customer.</p>'
        ),
    },
    {
        "name": "Quotation Rejected",
        "subject": "Returned for Revision: Quotation {{ doc.name }} — {{ doc.party_name }}",
        "response": _body(
            '<p style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;">'
            'Your quotation has been <b style="color:#b94d4d;">returned for revision</b>. '
            'Please review the approver comments on the document and resubmit.</p>'
        ),
    },
    {
        "name": "Quotation Confirmed at 100% Probability",
        "subject": "Quotation {{ doc.name }} confirmed at 100% probability",
        "response": _body(
            '<p style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;">'
            'This quotation has been confirmed at <b>100% probability</b> and is '
            'now visible to downstream teams (Procurement, Dispatch) for fulfilment.</p>'
        ),
    },
]


def execute():
    created = 0
    skipped = 0
    for tmpl in _TEMPLATES:
        if frappe.db.exists("Email Template", tmpl["name"]):
            skipped += 1
            continue
        frappe.get_doc({
            "doctype": "Email Template",
            "name": tmpl["name"],
            "subject": tmpl["subject"],
            "response": tmpl["response"],
            "use_html": 1,
        }).insert(ignore_permissions=True)
        created += 1
    if created:
        frappe.db.commit()
    print(f"[seed_quotation_email_templates] created={created} already_present={skipped}")
