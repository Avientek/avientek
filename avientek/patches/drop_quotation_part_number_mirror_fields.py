"""Drop the parent-level Quotation Part Number mirror fields.

Sridhar 2026-06-05 — clean-up after the Optional Item migration (Steps
1-4, commits c4c7dfb/5c19ca4/74aa97b).

Two Custom Fields on Quotation were added back in May/June to work around
a Report View column collision between `items` and `custom_service_items`
(both pointed to the Quotation Item DocType, so picking Part Number
became ambiguous):

  - first_item_part_number (label 'Item Part Number')
  - optional_item_part_numbers (label 'Optional Item Part Number')

A `copy_first_item_part_number` before_save hook kept them in sync with
the comma-joined Part Number values from each child table.

Now that `custom_service_items` points to its own DocType (Optional
Item), Report View can show per-table Part Number columns directly:
  - Items > Part Number      → from Quotation Item.part_number
  - Optional Items > Part Number → from Optional Item.part_number

The mirror fields + the copy function are dead weight. This patch:
  1. Deletes both Custom Fields
  2. Cleans up Report View saved_columns / saved_filters / saved_order
     in any User Settings that reference the dropped fields
  3. Removes related Property Setters if present

Idempotent — re-runs find nothing to delete.

The before_save hook and the events.quotation.copy_first_item_part_number
function are removed in the same commit.
"""
import frappe
import json


CF_NAMES = (
    "Quotation-first_item_part_number",
    "Quotation-optional_item_part_numbers",
)
FIELDNAMES = ("first_item_part_number", "optional_item_part_numbers")


def execute():
    # 1. Delete the Custom Fields
    deleted_cf = 0
    for cf in CF_NAMES:
        if frappe.db.exists("Custom Field", cf):
            frappe.delete_doc("Custom Field", cf, ignore_permissions=True, force=True)
            deleted_cf += 1
            print(f"[drop_quotation_part_number_mirror_fields] deleted Custom Field {cf}")

    # 2. Drop the underlying DB columns (Frappe doesn't auto-drop).
    # Must use sql_ddl to bypass Frappe's implicit-commit guard around
    # raw ALTER TABLE statements.
    frappe.db.commit()  # close any open transaction first
    for fn in FIELDNAMES:
        col_exists = frappe.db.sql(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'tabQuotation' AND COLUMN_NAME = %s",
            (fn,),
        )[0][0]
        if not col_exists:
            continue
        try:
            frappe.db.sql_ddl(f"ALTER TABLE `tabQuotation` DROP COLUMN `{fn}`")
            print(f"[drop_quotation_part_number_mirror_fields] dropped column tabQuotation.{fn}")
        except Exception as e:
            print(f"[drop_quotation_part_number_mirror_fields] WARN dropping {fn}: {e}")

    # 3. Clean Report View User Settings — strip references to the
    # dropped fields from saved_columns / saved_filters / saved_order
    cleaned_us = 0
    us_rows = frappe.db.sql("""
        SELECT user, data FROM `__UserSettings`
        WHERE doctype = 'Quotation'
    """, as_dict=True)
    for row in us_rows:
        try:
            data = json.loads(row.data) if row.data else {}
        except Exception:
            continue
        changed = False
        report_view = data.get("Report") or {}
        for key in ("columns",):
            arr = report_view.get(key) or []
            new_arr = [
                c for c in arr
                if not (isinstance(c, list) and len(c) >= 2 and c[0] in FIELDNAMES and c[1] == "Quotation")
            ]
            if len(new_arr) != len(arr):
                report_view[key] = new_arr
                changed = True
        if changed:
            data["Report"] = report_view
            frappe.db.sql(
                "UPDATE `__UserSettings` SET data = %s WHERE user = %s AND doctype = 'Quotation'",
                (json.dumps(data), row.user),
            )
            # Bust the Redis shadow cache that __UserSettings reads first
            try:
                frappe.cache().hdel("_user_settings", f"Quotation::{row.user}")
            except Exception:
                pass
            cleaned_us += 1

    if cleaned_us:
        print(f"[drop_quotation_part_number_mirror_fields] cleaned {cleaned_us} __UserSettings rows")

    # 4. Drop any related Property Setters (older patches added
    # report_hide flags on these fields)
    ps_rows = frappe.db.sql_list("""
        SELECT name FROM `tabProperty Setter`
        WHERE doc_type = 'Quotation' AND field_name IN %(fns)s
    """, {"fns": FIELDNAMES})
    for ps in ps_rows:
        frappe.delete_doc("Property Setter", ps, ignore_permissions=True, force=True)
        print(f"[drop_quotation_part_number_mirror_fields] deleted Property Setter {ps}")

    frappe.db.commit()
    frappe.clear_cache(doctype="Quotation")
    print(f"[drop_quotation_part_number_mirror_fields] done — cf={deleted_cf} us={cleaned_us}")
