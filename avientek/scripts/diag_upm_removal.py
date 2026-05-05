"""Confirm UPM / UPD DocTypes are gone post-migrate."""
import frappe


def run():
    for dt in ("User Permission Manager", "User Permission Details"):
        exists = bool(frappe.db.exists("DocType", dt))
        table = frappe.db.table_exists(dt)
        print(f"  DocType '{dt}': "
              f"{'STILL EXISTS' if exists else 'gone'} (table_exists={table})")

    cf = "User Permission-user_permission_manager"
    print(f"  Custom Field '{cf}': "
          f"{'still here' if frappe.db.exists('Custom Field', cf) else 'gone'}")

    # Sample User Permission rows — the back-pointer column should be gone
    cols = [r[0] for r in frappe.db.sql(
        "SHOW COLUMNS FROM `tabUser Permission`")]
    has_col = "user_permission_manager" in cols
    print(f"  tabUser Permission.user_permission_manager column: "
          f"{'still here' if has_col else 'gone'}")

    # Patch log
    p = frappe.db.exists(
        "Patch Log",
        {"patch": "avientek.patches.remove_user_permission_manager"},
    )
    print(f"  patch run record: {'YES' if p else 'NO'}")

    # Run the smoke test of global filter to make sure nothing broke
    print("\n  Running global UP filter smoke...")
    from avientek.scripts.smoke_global_up_filter import run as smoke
    res = smoke()
    print(f"  smoke result: override_ok={res.get('override_ok')} "
          f"rb_pass={res.get('report_builder_pass')} "
          f"qr_pass={res.get('query_report_pass')}")
