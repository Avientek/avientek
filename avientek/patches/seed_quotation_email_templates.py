"""Seed 4 professional Email Templates for the Quotation approval flow.

Created once if missing — never overwrites existing rows so admins can
edit the wording in /app/email-template without losing changes on next
migrate.

Used by `avientek.api.quotation_high_probability._render_quotation_email`
(prob-100 alert) and the upcoming workflow-state notification hook
(approval-request / approved / rejected).
"""

import frappe


_BRAND_HEADER = (
    '<table width="100%" cellpadding="0" cellspacing="0" '
    'style="background:#1f4e3d;color:#f7f1e3;'
    'font-family:Segoe UI,Arial,sans-serif;">'
    '<tr><td style="padding:14px 22px;font-size:18px;font-weight:600;'
    'letter-spacing:0.5px;">AVIENTEK</td>'
    '<td align="right" style="padding:14px 22px;font-size:11px;'
    'color:#d4b95e;">{{ doc.doctype }} {{ doc.name }}</td></tr></table>'
)

_DETAIL_TABLE = (
    '<table width="100%" cellpadding="0" cellspacing="0" '
    'style="border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;'
    'font-size:13px;margin-top:18px;">'
    '<tr><td style="padding:6px 0;color:#666;width:38%;">Customer</td>'
    '<td style="padding:6px 0;font-weight:500;">'
    '{{ doc.party_name or doc.quotation_to or "—" }}</td></tr>'
    '<tr><td style="padding:6px 0;color:#666;">Salesperson</td>'
    '<td style="padding:6px 0;">{{ doc.owner }}</td></tr>'
    '<tr><td style="padding:6px 0;color:#666;">Grand Total</td>'
    '<td style="padding:6px 0;font-weight:600;color:#1f4e3d;">'
    '{{ "{:,.2f}".format(doc.grand_total or 0) }} {{ doc.currency or "" }}</td></tr>'
    '<tr><td style="padding:6px 0;color:#666;">Probability</td>'
    '<td style="padding:6px 0;">{{ doc.probability or 0 }}%</td></tr>'
    '<tr><td style="padding:6px 0;color:#666;">Valid Till</td>'
    '<td style="padding:6px 0;">{{ doc.valid_till or "—" }}</td></tr>'
    '</table>'
)

_BUTTON = (
    '<p style="margin-top:24px;">'
    '<a href="{{ frappe.utils.get_url() }}/app/quotation/{{ doc.name }}" '
    'style="display:inline-block;padding:10px 22px;background:#d4b95e;'
    'color:#1f4e3d;text-decoration:none;font-weight:600;'
    'font-family:Segoe UI,Arial,sans-serif;font-size:13px;'
    'border-radius:3px;">Open Quotation →</a></p>'
)

_FOOTER = (
    '<p style="margin-top:30px;font-size:11px;color:#999;'
    'font-family:Segoe UI,Arial,sans-serif;border-top:1px solid #eee;'
    'padding-top:12px;">'
    'This is an automated notification from Avientek ERP. To turn these '
    'emails off, edit <b>Avientek Settings → Notifications</b>.</p>'
)


def _body(intro_html):
    return (
        '<div style="max-width:640px;margin:0 auto;background:#fdfaf3;'
        'padding:0 0 24px 0;">'
        + _BRAND_HEADER
        + '<div style="padding:24px;">'
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
            'Your quotation has been <b style="color:#1f4e3d;">approved</b> and is '
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
