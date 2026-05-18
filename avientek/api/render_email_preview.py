"""Render all 4 quotation Email Templates against a real quote and
write the HTML to /tmp for browser preview."""

import os
import frappe


def run():
    rows = frappe.db.sql(
        """select name from `tabQuotation`
           where docstatus = 1
             and sales_person is not null and sales_person != ''
             and grand_total > 0
           limit 1""",
        as_dict=False,
    )
    if not rows:
        print("No suitable quote found")
        return
    doc = frappe.get_doc("Quotation", rows[0][0])

    templates = [
        "Quotation Approval Required",
        "Quotation Approved",
        "Quotation Rejected",
        "Quotation Confirmed at 100% Probability",
    ]

    out_dir = "/tmp/avientek_email_previews"
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for name in templates:
        tmpl = frappe.db.get_value(
            "Email Template", name, ["subject", "response"], as_dict=True
        )
        if not tmpl:
            print(f"Template not found: {name}")
            continue
        ctx = {"doc": doc}
        subject = frappe.render_template(tmpl.subject or "", ctx)
        body = frappe.render_template(tmpl.response or "", ctx)
        html = (
            f"<!doctype html><html><head><meta charset=utf-8>"
            f"<title>{subject}</title>"
            f"<style>body{{background:#eee;margin:0;padding:30px;font-family:Segoe UI,Arial,sans-serif;}}"
            f".meta{{max-width:640px;margin:0 auto 16px;background:#fff;padding:10px 14px;border:1px solid #ddd;font-size:12px;color:#666;}}"
            f".meta b{{color:#333;}}"
            f"</style></head><body>"
            f"<div class='meta'><b>From:</b> noreply@avientek.com<br>"
            f"<b>To:</b> &lt;approver@avientek.com&gt;<br>"
            f"<b>Subject:</b> {subject}</div>"
            f"{body}"
            f"</body></html>"
        )
        slug = name.lower().replace(" ", "_")
        path = os.path.join(out_dir, f"{slug}.html")
        with open(path, "w") as f:
            f.write(html)
        written.append((name, path, subject))

    print(f"\nRendered against quote: {doc.name}")
    print(f"  Customer: {doc.party_name}")
    print(f"  Grand Total: {doc.grand_total} {doc.currency}")
    print(f"  Sales Person: {doc.get('sales_person')}\n")
    for name, path, subject in written:
        print(f"  {name}")
        print(f"    Subject: {subject}")
        print(f"    File:    {path}")
