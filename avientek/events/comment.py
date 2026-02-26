import re
import frappe
from frappe.utils import get_fullname
from frappe.desk.doctype.notification_log import notification_log as nl


def after_insert(doc, method):
    """When a comment with @mentions is posted, create a Bell Notification
    and a ToDo for each mentioned user. No emails are sent."""
    if doc.comment_type != "Comment":
        return

    if not doc.content:
        return

    mentioned_emails = re.findall(
        r'class="mention"[^>]*data-id="([^"]+)"', doc.content
    )
    if not mentioned_emails:
        return

    mentioned_emails = list(set(mentioned_emails))
    commenter = doc.comment_email or frappe.session.user
    commenter_name = get_fullname(commenter)

    ref_doctype = doc.reference_doctype
    ref_name = doc.reference_name
    subject = f"{commenter_name} mentioned you in {ref_doctype} {ref_name}"

    # Strip HTML for plain-text preview
    plain_text = re.sub(r"<[^>]+>", "", doc.content).strip()
    if len(plain_text) > 200:
        plain_text = plain_text[:200] + "..."

    for email in mentioned_emails:
        if email == commenter:
            continue

        if not frappe.db.exists("User", email):
            continue

        # Bell Notification — temporarily disable email sending
        notification = frappe.new_doc("Notification Log")
        notification.for_user = email
        notification.from_user = commenter
        notification.subject = subject
        notification.type = "Mention"
        notification.document_type = ref_doctype
        notification.document_name = ref_name
        notification.email_content = plain_text

        _original_send = nl.send_notification_email
        nl.send_notification_email = lambda doc: None
        try:
            notification.insert(ignore_permissions=True)
        finally:
            nl.send_notification_email = _original_send

        # ToDo with link back to the document
        ref_url = f"/app/{ref_doctype.lower().replace(' ', '-')}/{ref_name}"
        todo_description = (
            f'{commenter_name} mentioned you in '
            f'<a href="{ref_url}">{ref_doctype} {ref_name}</a>'
            f'<br><blockquote>{plain_text}</blockquote>'
        )

        todo = frappe.get_doc({
            "doctype": "ToDo",
            "allocated_to": email,
            "assigned_by": commenter,
            "reference_type": ref_doctype,
            "reference_name": ref_name,
            "description": todo_description,
            "status": "Open",
            "priority": "Medium",
        })
        todo.insert(ignore_permissions=True)
