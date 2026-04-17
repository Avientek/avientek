"""Ensure Trust Receipt and LC exist as Mode of Payment records.

Payment Request Form uses Mode of Payment as the Link target for the
`payment_mode` field. Finance team needs both options available.
"""

import frappe


_MODES = [
    ("Trust Receipt", "Bank", "TR"),
    ("LC", "Bank", "LC"),
]


def execute():
    for name, mop_type, short in _MODES:
        if frappe.db.exists("Mode of Payment", name):
            print(f"[add_payment_modes_tr_lc] {name} already present")
            continue
        doc = frappe.new_doc("Mode of Payment")
        doc.mode_of_payment = name
        doc.type = mop_type
        doc.enabled = 1
        doc.insert(ignore_permissions=True)
        print(f"[add_payment_modes_tr_lc] created {name}")
    frappe.db.commit()
