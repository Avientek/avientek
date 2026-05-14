# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Bank Account event hooks.

import frappe


def auto_link_internal_company_account(doc, method=None):
    """Auto-tick `is_company_account` on save when the Bank Account is
    linked to an Internal Customer (Customer.is_internal_customer=1) or
    an Internal Supplier (Supplier.is_internal_supplier=1).

    Why: those parties represent another Avientek group entity, so their
    bank accounts ARE company accounts from the group's perspective.
    Without this flag, the account is hidden from every standard ERPNext
    picker that filters `is_company_account=1` (bank reconciliation,
    payment entries, journal entries) — Jithin 2026-05-17.

    Idempotent: never unsets the flag, only sets it.
    """
    if doc.is_company_account:
        return
    if not doc.party_type or not doc.party:
        return

    is_internal = False
    if doc.party_type == "Customer":
        is_internal = bool(
            frappe.db.get_value("Customer", doc.party, "is_internal_customer")
        )
    elif doc.party_type == "Supplier":
        is_internal = bool(
            frappe.db.get_value("Supplier", doc.party, "is_internal_supplier")
        )

    if is_internal:
        doc.is_company_account = 1
