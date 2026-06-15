"""Flip Payment Request Form.supplier_address.allow_on_submit to 1
via Property Setter so Finance Controllers can edit the Party Address
on submitted PRFs that are in Approved Level 2 (or earlier post-submit
states).

Sridhar 2026-06-15 — PRF Enhancement doc §3 ("Post-Approval Field
Editing"): the list of non-financial fields editable by FC after L2
approval includes "Address". On local 2026-06-15 the field has
allow_on_submit = 0, so Frappe rejects every PUT to the address
picker on a submitted doc regardless of our role-based JS unlock.

Property Setter is the idempotent, migration-safe way to flip this
without editing the upstream Frappe-shipped doctype JSON.

Frozen-field stewardship:
  - supplier_bank_account.allow_on_submit was already 1 (verified
    2026-06-15) — no flip needed.
  - issued_bank, payment_mode, cheque_date are already 1.
  - All amount/line-item/tax fields stay 0 and the existing
    `_PRF_LOCKED_FIELDS_AFTER_SUBMIT` + `_guard_bank_edits_after_submit`
    keep them frozen, plus terminal-state freeze for everyone except
    System Manager.
"""

import frappe


_DOCTYPE = "Payment Request Form"
_FIELDNAME = "supplier_address"


def execute():
    if not frappe.db.exists("DocType", _DOCTYPE):
        return

    # Confirm field exists before patching.
    if not frappe.db.exists(
        "DocField",
        {"parent": _DOCTYPE, "fieldname": _FIELDNAME},
    ):
        return

    # Idempotent Property Setter: target the single (doctype, field,
    # property) tuple. Frappe's make_property_setter handles
    # insert-or-update internally.
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter

    make_property_setter(
        _DOCTYPE,
        _FIELDNAME,
        property="allow_on_submit",
        value=1,
        property_type="Check",
        for_doctype=False,
    )
    frappe.clear_cache(doctype=_DOCTYPE)
