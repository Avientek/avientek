"""Ensure the "Sales User" role has read/write/create/submit on Sales
Invoice at permlevel 0.

Diag (debug_user_visibility for testqcs@gmail.com) showed the Sales
User role was missing every DocPerm on Sales Invoice — only the "All"
role at permlevel=1 was present. That meant restricted users like
testqcs couldn't see any Sales Invoices beyond the handful they
created themselves (Frappe's owner fallback), so the User-Permission
Sales Person = MIDHUN filter had nothing to act on.

This patch creates a Custom DocPerm for the Sales User role on Sales
Invoice with read/write/create/submit/print/email/report/share at
permlevel 0 and if_owner=0, then clears the doctype cache so Frappe
picks up the new permission map.

Idempotent — re-running is a no-op once the permission exists.
"""

import frappe


_ROLE = "Sales User"
_DT = "Sales Invoice"


def execute():
    if not frappe.db.exists("Role", _ROLE):
        print(f"[ensure_sales_user_sales_invoice_perm] Role '{_ROLE}' missing, skip")
        return

    existing = frappe.db.sql(
        """SELECT name FROM `tabCustom DocPerm`
           WHERE parent=%s AND role=%s AND permlevel=0 AND IFNULL(if_owner,0)=0""",
        (_DT, _ROLE), pluck="name",
    )
    if existing:
        # Ensure key flags are set correctly even if the record existed
        for name in existing:
            frappe.db.set_value("Custom DocPerm", name, {
                "read": 1,
                "write": 1,
                "create": 1,
                "submit": 1,
                "cancel": 1,
                "print": 1,
                "email": 1,
                "report": 1,
                "share": 1,
            }, update_modified=False)
        print(f"[ensure_sales_user_sales_invoice_perm] updated {len(existing)} existing Custom DocPerm")
    else:
        doc = frappe.new_doc("Custom DocPerm")
        doc.parent = _DT
        doc.parenttype = "DocType"
        doc.parentfield = "permissions"
        doc.role = _ROLE
        doc.permlevel = 0
        doc.if_owner = 0
        doc.read = 1
        doc.write = 1
        doc.create = 1
        doc.submit = 1
        doc.cancel = 1
        doc.print = 1
        doc.email = 1
        doc.report = 1
        doc.share = 1
        doc.insert(ignore_permissions=True)
        print(f"[ensure_sales_user_sales_invoice_perm] created Custom DocPerm: {doc.name}")

    frappe.db.commit()
    frappe.clear_cache(doctype=_DT)
