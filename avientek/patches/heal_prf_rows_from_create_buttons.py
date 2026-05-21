"""Heal PRF payment_references rows created by the 'Create → Payment
Request Form' buttons on PI / SI / JV / EC / PE.

Jithin escalation 2026-05-21: every Create→PRF path except Purchase
Order (fix-forwarded morning of 2026-05-21, commit 136d1f3) had the
same bug — they placed the source's Frappe doc name into
`reference_name` and either left `document_reference` empty or
populated it with an unrelated link (e.g. the PI's first item's
purchase_order, or the JV's custom_sales_invoice).

This violated the canonical PRF row contract (established 2026-05-18):
  - reference_name      → free-text supplier/customer bill_no
  - document_reference  → Frappe doc name of the referenced doc
  - bill_no             → mirrors reference_name for list-view sorting

Fix-forwards shipped today across all 5 paths. This patch heals
historical rows so existing PRFs surface the right values on the
form, print preview, Combined PDF and Connections panel.

Repair logic (per reference_doctype):

  Purchase Invoice (created via PI Create button):
    Symptom: reference_name = '<Frappe PI name>'  (e.g. PINV-…)
             document_reference = '<linked PO name>' or NULL
    Fix:     If reference_name is a valid Frappe Purchase Invoice
             name:
               - document_reference = reference_name
               - bill_no = the PI's bill_no
               - reference_name = the PI's bill_no (so the user-
                 visible "Invoice" column shows the supplier
                 invoice number, not the Frappe doc name)

  Sales Invoice / Credit Note (created via SI Create button):
    Symptom: reference_name = '<Frappe SI name>'
             document_reference = NULL
    Fix:     If reference_name is a valid SI: move to
             document_reference, clear reference_name.

  Journal Entry (created via JV Create button):
    Symptom: reference_name = '<Frappe JV name>'
             document_reference = '<custom_sales_invoice>' or NULL
    Fix:     If reference_name is a valid JV: move to
             document_reference, clear reference_name.

  Expense Claim (created via EC Create button):
    Symptom: reference_name = '<Frappe EC name>'
             document_reference = NULL
    Fix:     If reference_name is a valid EC: move to
             document_reference, clear reference_name.

  Payment Entry (created via PE Create button):
    Symptom: reference_name = '<Frappe PE name>'
             document_reference = NULL
    Fix:     If reference_name is a valid PE: move to
             document_reference, clear reference_name.

Idempotent — re-runs find no matching rows (every row's
reference_name is now blank or a bill_no, never a Frappe doc name).
Rows that already have document_reference populated correctly
(e.g. created via the Get Outstanding Invoice picker, which has
always followed the canonical contract) are untouched.
"""

import frappe


_DOCTYPES = (
    "Purchase Invoice",
    "Sales Invoice",
    "Credit Note",  # routes through Sales Invoice
    "Journal Entry",
    "Expense Claim",
    "Payment Entry",
)

# Credit Note rows reference Sales Invoice docs (is_return=1).
_CHILD_TARGET = {
    "Purchase Invoice": "Purchase Invoice",
    "Sales Invoice":    "Sales Invoice",
    "Credit Note":      "Sales Invoice",
    "Journal Entry":    "Journal Entry",
    "Expense Claim":    "Expense Claim",
    "Payment Entry":    "Payment Entry",
}


def execute():
    for ref_type in _DOCTYPES:
        target_doctype = _CHILD_TARGET[ref_type]

        # Candidate rows: where reference_name LOOKS like a Frappe doc
        # name for `target_doctype` AND document_reference is empty OR
        # different from reference_name. Avoid heavy LIKE patterns —
        # frappe.db.exists() per candidate is cheap and unambiguous.
        rows = frappe.db.sql(
            """
            SELECT name, parent, reference_name, document_reference
            FROM `tabPayment Request Reference`
            WHERE reference_doctype = %s
              AND IFNULL(reference_name, '') != ''
              AND (
                  IFNULL(document_reference, '') = ''
                  OR document_reference != reference_name
              )
            """,
            (ref_type,),
            as_dict=True,
        )

        healed = 0
        skipped = 0
        for r in rows:
            ref_name = (r["reference_name"] or "").strip()
            if not ref_name:
                continue
            if not frappe.db.exists(target_doctype, ref_name):
                skipped += 1
                continue

            updates = {
                "document_reference": ref_name,
            }
            if ref_type in ("Purchase Invoice",):
                supplier_bill_no = (
                    frappe.db.get_value(target_doctype, ref_name, "bill_no") or ""
                )
                updates["reference_name"] = supplier_bill_no
                updates["bill_no"] = supplier_bill_no
            else:
                updates["reference_name"] = ""
                updates["bill_no"] = ""

            frappe.db.set_value(
                "Payment Request Reference",
                r["name"],
                updates,
                update_modified=False,
            )
            healed += 1

        if healed:
            frappe.db.commit()
        print(
            f"[heal_prf_rows_from_create_buttons] {ref_type}: "
            f"candidate={len(rows)} healed={healed} "
            f"skipped_invalid={skipped}"
        )
