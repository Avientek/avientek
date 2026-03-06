from frappe.core.doctype.comment.comment import Comment


class CustomComment(Comment):
    def after_insert(self):
        # Skip notify_mentions (which tries to send email).
        # Bell notifications and ToDos are handled by
        # avientek.events.comment.after_insert instead.
        self.notify_change("add")
