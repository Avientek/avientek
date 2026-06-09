"""Sridhar 2026-06-09: relax the Document Approval section visibility on
Quotation so it shows for ALL submitted quotes, not just probability >= 75.

Background: the section, Request for Update checkbox, and Cancellation Check
checkbox all had:
  depends_on: eval:doc.docstatus==1 && (doc.probability>=75 || ['75%','80%','85%','90%','95%','100%'].indexOf(doc.probabilities)>=0)

That hid the section entirely for low-probability quotes. But a low-probability
quote can still be Approved (margin OK → auto-approve), and users still need to
cancel them sometimes. Sridhar reported QN-LTD-26-02209 (Avientek PVT LTD,
probability 10%) — no cancellation option visible.

Fix: simplify depends_on to `eval:doc.docstatus==1`. The workflow itself
already gates the actual cancel transitions, so the form-level gate was
redundant + harmful.

Patch updates the 3 Custom Field records on existing sites; fresh installs
get the new depends_on from custom_field.json.
"""

import frappe

NEW_DEPENDS_ON = "eval:doc.docstatus==1"
NEW_SECTION_DESC = (
    "Available on any submitted Quotation. Tick Request for Update to revise "
    "or Cancellation Check to cancel the quote."
)

AFFECTED_FIELDS = [
    "Quotation-custom_document_approval",
    "Quotation-custom_request_for_update",
    "Quotation-custom_cancellation_check",
]


def execute():
    print("[relax_document_approval_visibility] start")
    updated = 0
    for cf_name in AFFECTED_FIELDS:
        if not frappe.db.exists("Custom Field", cf_name):
            print(f"  skip — {cf_name} not on this site")
            continue
        current = frappe.db.get_value("Custom Field", cf_name, "depends_on")
        if current == NEW_DEPENDS_ON:
            print(f"  {cf_name}: already at new depends_on, no change")
            continue
        frappe.db.set_value(
            "Custom Field", cf_name, "depends_on", NEW_DEPENDS_ON,
            update_modified=False,
        )
        updated += 1
        print(f"  {cf_name}: depends_on updated")

    # Section description was misleading after the visibility change;
    # update only the section's description, not the checkboxes (theirs
    # remain accurate).
    section_name = "Quotation-custom_document_approval"
    if frappe.db.exists("Custom Field", section_name):
        cur_desc = frappe.db.get_value("Custom Field", section_name, "description") or ""
        if "75%" in cur_desc:
            frappe.db.set_value(
                "Custom Field", section_name, "description", NEW_SECTION_DESC,
                update_modified=False,
            )
            print(f"  {section_name}: description updated")

    frappe.db.commit()
    frappe.clear_cache(doctype="Quotation")
    print(f"[relax_document_approval_visibility] done — {updated} fields updated")
