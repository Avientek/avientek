# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Back-fill is_company_account=1 on Bank Accounts whose linked party is
# an Internal Customer / Internal Supplier.
#
# Jithin 2026-05-17: the new bank_account.auto_link_internal_company_account
# validate hook only fires on save — existing Bank Account records keep
# their stale is_company_account=0 until someone resaves them. This patch
# fills the gap in one pass. Idempotent (UPDATE only flips 0 → 1, never
# touches rows already at 1).

import frappe


def execute():
    customer_updated = frappe.db.sql(
        """
        UPDATE `tabBank Account` ba
        JOIN `tabCustomer` c
            ON ba.party_type = 'Customer' AND ba.party = c.name
        SET ba.is_company_account = 1
        WHERE IFNULL(c.is_internal_customer, 0) = 1
          AND IFNULL(ba.is_company_account, 0) = 0
        """
    )

    supplier_updated = frappe.db.sql(
        """
        UPDATE `tabBank Account` ba
        JOIN `tabSupplier` s
            ON ba.party_type = 'Supplier' AND ba.party = s.name
        SET ba.is_company_account = 1
        WHERE IFNULL(s.is_internal_supplier, 0) = 1
          AND IFNULL(ba.is_company_account, 0) = 0
        """
    )

    frappe.db.commit()
    print(
        "backfill_is_company_account_internal_party: "
        f"customer_rows={customer_updated} supplier_rows={supplier_updated}"
    )
