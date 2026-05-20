"""Heal PRF payment_references rows created via the
'Create -> Payment Request Form' button on Purchase Order (server
method `avientek.events.purchase_order.create_payment_request`).

Jithin 2026-05-21 (AVFZC-02174 case): the prior code path put the
PO's first-item linked Sales Order into `document_reference`, and the
PO name into `reference_name`. Both violate the canonical contract
(document_reference must match reference_doctype). Fix-forward
shipped same day in `events/purchase_order.py`; this patch repairs
historical rows so existing PRFs surface the right values too.

Repair logic:
  For each Payment Request Reference row where:
    reference_doctype = 'Purchase Order'
    AND reference_name LIKE 'PO-%'          (PO leaked into reference_name)
    AND document_reference NOT LIKE 'PO-%'   (something else in doc_ref)
  →  move reference_name to document_reference, blank out reference_name.

Idempotent — re-runs find no matching rows.
"""

import frappe


def execute():
    # Find broken rows: reference_doctype=PO with PO-name in reference_name
    # and non-PO-name (e.g. SO-name) in document_reference.
    rows = frappe.db.sql(
        """
        SELECT name, parent, reference_name, document_reference
        FROM `tabPayment Request Reference`
        WHERE reference_doctype = 'Purchase Order'
          AND reference_name LIKE 'PO-%'
          AND (
              document_reference IS NULL
              OR document_reference = ''
              OR document_reference NOT LIKE 'PO-%'
          )
        """,
        as_dict=True,
    )

    if not rows:
        print("[fix_prf_rows_from_po_create_payment_request] no broken rows found")
        return

    healed = 0
    for r in rows:
        # Sanity: confirm reference_name is actually a real PO before moving it
        if not frappe.db.exists("Purchase Order", r["reference_name"]):
            print(
                f"  skip {r['name']} (parent={r['parent']}): "
                f"reference_name {r['reference_name']!r} not a real PO"
            )
            continue
        frappe.db.set_value(
            "Payment Request Reference",
            r["name"],
            {
                "document_reference": r["reference_name"],
                "reference_name": "",
            },
            update_modified=False,
        )
        healed += 1
        print(
            f"  healed row {r['name']} on {r['parent']}: "
            f"doc_ref {r['document_reference']!r} -> {r['reference_name']!r}, "
            f"reference_name cleared"
        )

    if healed:
        frappe.db.commit()
    print(
        f"[fix_prf_rows_from_po_create_payment_request] healed={healed} "
        f"of {len(rows)} candidate rows"
    )
