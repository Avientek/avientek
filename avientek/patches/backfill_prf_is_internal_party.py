# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Sammish 2026-05-15 — split-out backfill of `is_internal_party` on
# existing PRFs.
#
# Originally this backfill lived in `prf_workflow_check_payment_type_directly`,
# but that patch is registered pre-model-sync — on a fresh Frappe Cloud
# migrate the `is_internal_party` Custom Field doesn't exist when the
# patch runs, so the UPDATE crashes the migrate.
#
# Split into a separate post-model-sync patch so it runs AFTER schema
# sync has brought the column in. Idempotent — only flips 0 → 1.

import frappe


def execute():
    if not frappe.db.has_column("Payment Request Form", "is_internal_party"):
        print(
            "[backfill_prf_is_internal_party] is_internal_party column still missing — "
            "Custom Field fixture may not have synced; aborting (re-run next migrate)"
        )
        return

    it_rows = frappe.db.sql(
        """UPDATE `tabPayment Request Form`
           SET is_internal_party = 1
           WHERE payment_type = 'Internal Transfer'
             AND COALESCE(is_internal_party, 0) = 0"""
    )
    it_affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

    cust_rows = frappe.db.sql(
        """UPDATE `tabPayment Request Form` prf
           JOIN `tabCustomer` c ON c.name = prf.party
           SET prf.is_internal_party = 1
           WHERE prf.party_type = 'Customer'
             AND c.is_internal_customer = 1
             AND COALESCE(prf.is_internal_party, 0) = 0"""
    )
    cust_affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

    sup_rows = frappe.db.sql(
        """UPDATE `tabPayment Request Form` prf
           JOIN `tabSupplier` s ON s.name = prf.party
           SET prf.is_internal_party = 1
           WHERE prf.party_type = 'Supplier'
             AND s.is_internal_supplier = 1
             AND COALESCE(prf.is_internal_party, 0) = 0"""
    )
    sup_affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

    frappe.db.commit()
    print(
        f"[backfill_prf_is_internal_party] backfill complete — "
        f"IT={it_affected} internal_customer={cust_affected} internal_supplier={sup_affected}"
    )
