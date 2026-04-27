"""Set ignore_user_permissions=1 on the custom_sales_person Link field
across Sales Invoice / Sales Order / Delivery Note / POS Invoice.

Reported 2026-04-26 (ticket): user dispatch.india1@avientek.com could
not access Delivery Note LTD-26-27-00093 — error popup said
"You are not allowed to access this Sales Invoice record because it is
linked to Sales Person 'empty' in field Sales Person ... Sales Invoice
- None ... You need the 'create' permission on Sales Invoice".

Root cause: clicking Create → Sales Invoice from a DN runs ERPNext's
make_sales_invoice mapper. It copies the Sales Team child rows but
does not populate the parent-level custom_sales_person field that
Avientek added (synced from sales_team[0] only on save by
sync_custom_sales_person). The new in-memory Sales Invoice has an
empty custom_sales_person.

System Settings here has apply_strict_user_permissions=1, so Frappe's
permissions.check_user_permission_on_link_fields enforces User
Permission even on EMPTY link fields. dispatch.india1 has User
Permissions on Sales Person → empty custom_sales_person fails the
check → error.

The real security boundary is the Sales Team child rows, enforced by
_combined_permission_query / has_permission_check. custom_sales_person
is a denormalized helper for the list filter — it should not enforce
User Permission. Set ignore_user_permissions=1 so Frappe skips it.

Idempotent — only updates fields whose flag is currently 0.
"""

import frappe


_TARGETS = [
    ("Sales Invoice", "custom_sales_person"),
    ("Sales Order", "custom_sales_person"),
    ("Delivery Note", "custom_sales_person"),
    ("POS Invoice", "custom_sales_person"),
]


def execute():
    changed = []
    for dt, fieldname in _TARGETS:
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": dt, "fieldname": fieldname},
            ["name", "ignore_user_permissions"],
            as_dict=True,
        )
        if not cf:
            print(f"[ignore_up_custom_sales_person] {dt}.{fieldname}: no Custom Field — skip")
            continue
        if cf.ignore_user_permissions == 1:
            print(f"[ignore_up_custom_sales_person] {dt}.{fieldname}: already set — skip")
            continue
        frappe.db.set_value("Custom Field", cf.name, "ignore_user_permissions", 1, update_modified=False)
        changed.append(f"{dt}.{fieldname}")
        print(f"[ignore_up_custom_sales_person] {dt}.{fieldname}: ignore_user_permissions 0 → 1")

    if changed:
        frappe.db.commit()
        # Clear meta cache so Frappe picks up the new flag without restart
        for dt, _fn in _TARGETS:
            try:
                frappe.clear_cache(doctype=dt)
            except Exception:
                pass
        print(f"[ignore_up_custom_sales_person] updated {len(changed)} field(s): {', '.join(changed)}")
    else:
        print("[ignore_up_custom_sales_person] no changes")
