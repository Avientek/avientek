"""ERP-TKT-7 — Re-backfill workflow_status drift on Quotation.

Sridhar 2026-06-01 ticket: list-view filter on "Cancellation Requested"
returned Cancelled docs. Investigation 2026-06-05 found 21 rows of
drift (workflow_state ≠ workflow_status) ALL modified AFTER the
2026-06-02 sync hook deploy. Drift accumulated because the hook only
wired on `validate`, and:
  - docstatus 1→2 (Cancel transitions): doc.cancel() doesn't call validate
  - some docstatus 1→1 paths use db.set_value bypassing validate

The companion code fix in this commit:
  - Adds sync_workflow_status to on_update_after_submit + on_cancel
  - Forces a direct db.set_value on the on_cancel path so the row
    actually persists (in-memory assignment is too late by then)

This patch does the one-time backfill of the existing drift. The
prior patch `sync_quotation_workflow_status_field` was correct but
ran once-per-site (memory: patches.txt seeders are once-only) and
new drift accumulated after. This is the v2 backfill — same SQL,
new module name so it runs again. Idempotent.
"""
import frappe


def execute():
    pre_drift = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabQuotation`
        WHERE IFNULL(workflow_state, '') != IFNULL(workflow_status, '')
    """)[0][0]
    print(f"[backfill_quotation_workflow_status_drift_v2] pre-drift rows: {pre_drift}")

    if pre_drift == 0:
        print("[backfill_quotation_workflow_status_drift_v2] no drift — no-op")
        return

    frappe.db.sql("""
        UPDATE `tabQuotation`
        SET workflow_status = workflow_state
        WHERE workflow_state IS NOT NULL
          AND (workflow_status IS NULL OR workflow_status != workflow_state)
    """)
    rowcount = frappe.db.sql("SELECT ROW_COUNT()")[0][0]
    frappe.db.commit()
    frappe.clear_cache(doctype="Quotation")

    post_drift = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabQuotation`
        WHERE IFNULL(workflow_state, '') != IFNULL(workflow_status, '')
    """)[0][0]
    print(f"[backfill_quotation_workflow_status_drift_v2] updated {rowcount} rows, post-drift={post_drift}")
