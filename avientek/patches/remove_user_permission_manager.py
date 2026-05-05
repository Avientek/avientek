"""Remove User Permission Manager + User Permission Details DocTypes
and all related artefacts.

Why
---
Sridhar 2026-05-05: the UPM/UPD doctypes were a parallel UI for managing
User Permissions in bulk, but the codebase has migrated to using the
native `tabUser Permission` directly + the new global filter
(avientek.api.report_permission_filter). UPM is dead weight that confuses
users showing up in DocType search and exposes a UI button on the User
form that no longer maps to a current workflow.

What this patch does (idempotent)
----------------------------------
1. Orphans linked User Permission rows by setting
   user_permission_manager = NULL (preserves the real perms — only
   removes the back-pointer to the soon-to-be-deleted UPM).
2. Direct-SQL deletes every UPM and UPD record (bypasses UPM.on_trash
   which would otherwise cascade-delete legitimate User Permission rows).
3. Removes the `User Permission-user_permission_manager` Custom Field.
4. Deletes the `User Permission Manager` and `User Permission Details`
   DocTypes themselves.
5. Clears the doctype cache.

Safe to re-run — every step is guarded by `frappe.db.exists` checks.
"""
import frappe


def execute():
    print("[remove_user_permission_manager] starting")

    # 1. Orphan linked User Permission rows (preserve the perm itself,
    #    only nullify the back-pointer field). Use direct SQL because
    #    the column may be missing if the custom field was never created.
    if frappe.db.exists("Custom Field",
                        "User Permission-user_permission_manager"):
        try:
            frappe.db.sql(
                "UPDATE `tabUser Permission` "
                "SET user_permission_manager = NULL "
                "WHERE IFNULL(user_permission_manager, '') <> ''"
            )
            print("[remove_user_permission_manager] orphaned UP back-pointers")
        except Exception as e:
            # Column might not exist on this site — non-fatal.
            print(f"[remove_user_permission_manager] orphan step skipped: {e}")

    # 2. Delete every UPM / UPD record via direct SQL — avoids triggering
    #    UPM.on_trash which would cascade-delete real User Permission rows.
    if frappe.db.table_exists("User Permission Details"):
        n_upd = frappe.db.sql("SELECT COUNT(*) FROM `tabUser Permission Details`")[0][0]
        frappe.db.sql("DELETE FROM `tabUser Permission Details`")
        print(f"[remove_user_permission_manager] deleted {n_upd} UPD rows")

    if frappe.db.table_exists("User Permission Manager"):
        n_upm = frappe.db.sql("SELECT COUNT(*) FROM `tabUser Permission Manager`")[0][0]
        frappe.db.sql("DELETE FROM `tabUser Permission Manager`")
        print(f"[remove_user_permission_manager] deleted {n_upm} UPM rows")

    # 3. Remove the custom field on User Permission that pointed at UPM.
    cf_name = "User Permission-user_permission_manager"
    if frappe.db.exists("Custom Field", cf_name):
        try:
            frappe.delete_doc("Custom Field", cf_name,
                              ignore_permissions=True, force=True)
            print(f"[remove_user_permission_manager] deleted Custom Field {cf_name}")
        except Exception as e:
            print(f"[remove_user_permission_manager] Custom Field delete failed: {e}")

    # 4. Delete the DocTypes themselves (parent first to satisfy FK in
    #    case Frappe checks; in practice both are independent tables).
    for dt in ("User Permission Manager", "User Permission Details"):
        if frappe.db.exists("DocType", dt):
            try:
                frappe.delete_doc("DocType", dt,
                                  ignore_permissions=True, force=True)
                print(f"[remove_user_permission_manager] deleted DocType {dt}")
            except Exception as e:
                # Last-resort manual cleanup if delete_doc fails (e.g.
                # because we already removed the python source files).
                print(f"[remove_user_permission_manager] delete_doc failed "
                      f"for {dt}: {e}; falling back to direct SQL")
                frappe.db.sql(
                    "DELETE FROM `tabDocField` WHERE parent = %s",
                    (dt,),
                )
                frappe.db.sql(
                    "DELETE FROM `tabDocType` WHERE name = %s",
                    (dt,),
                )
                table_safe = dt.replace(" ", "_").replace("-", "_")
                frappe.db.sql(f"DROP TABLE IF EXISTS `tab{dt}`")

    # 5. Drop the MySQL table-level artefacts (Frappe delete_doc on a
    #    DocType doesn't always DROP TABLE — make sure no orphaned tables
    #    or columns remain).
    for dt in ("User Permission Manager", "User Permission Details"):
        if frappe.db.table_exists(dt):
            frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{dt}`")
            print(f"[remove_user_permission_manager] dropped table tab{dt}")

    cols = [r[0] for r in frappe.db.sql(
        "SHOW COLUMNS FROM `tabUser Permission`")]
    if "user_permission_manager" in cols:
        try:
            frappe.db.sql_ddl(
                "ALTER TABLE `tabUser Permission` "
                "DROP COLUMN `user_permission_manager`"
            )
            print("[remove_user_permission_manager] dropped "
                  "tabUser Permission.user_permission_manager column")
        except Exception as e:
            print(f"[remove_user_permission_manager] column drop failed: {e}")

    frappe.clear_cache()
    frappe.db.commit()
    print("[remove_user_permission_manager] done")
