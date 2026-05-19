"""Make the Bank Account's "Party Details" section always visible.

Jithin 2026-05-19: he couldn't link an Internal Supplier to an
existing company Bank Account because the standard ERPNext doctype
has

    "depends_on": "eval:!doc.is_company_account"

on the section_break_11 ("Party Details") field. So the moment a
Bank Account is flagged as a company account, the party_type / party
fields disappear from the form. But the inter-company workflow needs
BOTH on the same record (the bank IS the company's own AND it serves
as the receiving bank when the represented entity acts as a
Supplier on a sister company's PRF).

This patch installs a Property Setter that blanks the depends_on so
the section is always shown. Other field semantics on Bank Account
are untouched — company / IBAN / account_type all stay as standard
ERPNext defines them.

Idempotent — `make_property_setter` updates if existing matches.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
    make_property_setter(
        "Bank Account",
        "section_break_11",
        "depends_on",
        "",  # always visible
        "Code",
        validate_fields_for_doctype=False,
    )
    print(
        "[show_bank_account_party_section_always] Party Details section "
        "is now always visible on Bank Account."
    )
