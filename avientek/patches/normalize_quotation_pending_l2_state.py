"""ERP-TKT-10 — Normalize duplicate L2 state names on Quotation.

Sridhar 2026-06-04 ticket: "Pending L2 approval showing in 2 different
format". Investigation 2026-06-05 found:
  - "Pending L2 Approval" (V3 canonical, style=Warning yellow) — 2 docs
  - "Pending Level 2 Approval" (legacy V2 name, NO style — renders as
    default grey badge) — 13 docs

Both states mean the same thing semantically, but they're distinct
Workflow State records so they appear as DIFFERENT options in the
filter dropdown AND render with different badge styles. Customer saw
both formats side-by-side and asked which was canonical.

Fix: migrate the 13 Quotation docs from the legacy V2 name to the V3
canonical name (workflow_state AND workflow_status). After this, no
Quotation doc is on the legacy name, the filter dropdown shows only
the V3 name, and all L2-pending badges render consistently yellow.

The V3 workflow seeder still has BRIDGE TRANSITIONS that reference the
legacy V2 name (so any pre-migration stuck quote could move forward).
Those bridges become dormant (no docs match) but stay intact for
safety. We do NOT delete the "Pending Level 2 Approval" Workflow State
record because the legacy "Quotation Final" V2 workflow still
references it; removing it would break that workflow's seeder.

Idempotent.
"""
import frappe


OLD_STATE = "Pending Level 2 Approval"
NEW_STATE = "Pending L2 Approval"


def execute():
    pre_state = frappe.db.count("Quotation", {"workflow_state": OLD_STATE})
    pre_status = frappe.db.count("Quotation", {"workflow_status": OLD_STATE})
    print(f"[normalize_quotation_pending_l2_state] pre: "
          f"workflow_state={pre_state}, workflow_status={pre_status} on {OLD_STATE!r}")

    if pre_state == 0 and pre_status == 0:
        print(f"[normalize_quotation_pending_l2_state] no docs to migrate")
        return

    frappe.db.sql(
        "UPDATE `tabQuotation` SET workflow_state = %(new)s WHERE workflow_state = %(old)s",
        {"old": OLD_STATE, "new": NEW_STATE},
    )
    state_rows = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

    frappe.db.sql(
        "UPDATE `tabQuotation` SET workflow_status = %(new)s WHERE workflow_status = %(old)s",
        {"old": OLD_STATE, "new": NEW_STATE},
    )
    status_rows = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

    frappe.db.commit()
    frappe.clear_cache(doctype="Quotation")

    # Purge __UserSettings Redis shadow so the filter dropdown picks up
    # the change without per-user session restart (Sridhar memory note
    # 2026-06-01: __UserSettings has a Redis hash that shadows DB reads).
    try:
        users = [r.name for r in frappe.db.sql(
            "SELECT name FROM `tabUser` WHERE enabled=1", as_dict=True
        )]
        for u in users:
            frappe.cache().hdel("_user_settings", f"Quotation::{u}")
        print(f"[normalize_quotation_pending_l2_state] purged __UserSettings for {len(users)} users")
    except Exception as e:
        print(f"[normalize_quotation_pending_l2_state] cache purge skipped: {e}")

    post_state = frappe.db.count("Quotation", {"workflow_state": OLD_STATE})
    post_status = frappe.db.count("Quotation", {"workflow_status": OLD_STATE})
    print(f"[normalize_quotation_pending_l2_state] migrated state={state_rows}, "
          f"status={status_rows}; post={post_state}/{post_status} on {OLD_STATE!r}")
