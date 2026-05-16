# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Jithin 2026-05-17 — clean up Payment Request Reference rows where
# the user changed `reference_doctype` from "Sales Order" (or similar)
# to "Purchase Order", typed a PO name into the editable
# `reference_name` field, but `document_reference` was left holding
# the stale SO from the earlier pick.
#
# Symptom on prod (AVFZC-02153/4/5, all from 2026-05-15):
#   reference_doctype  = "Purchase Order"
#   reference_name     = "PO-FZCO-26-XXXXX"
#   document_reference = "SO-FZCO-XX-XXXXX"  ← wrong
#
# Root cause was in the reference_doctype change handler — it didn't
# clear the prior document_reference / bill_no / reference_name when
# the type changed. Fix shipped in
# avientek/avientek/doctype/payment_request_form/payment_request_form.js
# (same commit as this patch).
#
# This patch repairs the already-broken rows: when reference_doctype
# is "Purchase Order" AND document_reference looks like an SO name
# AND reference_name looks like a PO name, copy reference_name into
# document_reference (the canonical link). Idempotent — only matches
# rows where the symptom is still present.

import frappe


def execute():
    affected = frappe.db.sql(
        """SELECT name, parent FROM `tabPayment Request Reference`
           WHERE reference_doctype = 'Purchase Order'
             AND document_reference LIKE 'SO-%'
             AND reference_name LIKE 'PO-%'""",
        as_dict=True,
    )
    if not affected:
        print("fix_prf_po_rows_with_stale_so_document_reference: no rows to fix")
        return

    frappe.db.sql(
        """UPDATE `tabPayment Request Reference`
           SET document_reference = reference_name
           WHERE reference_doctype = 'Purchase Order'
             AND document_reference LIKE 'SO-%'
             AND reference_name LIKE 'PO-%'"""
    )
    frappe.db.commit()

    print(
        "fix_prf_po_rows_with_stale_so_document_reference: "
        f"fixed {len(affected)} rows — "
        + ", ".join(f"{r['parent']} ({r['name']})" for r in affected)
    )
