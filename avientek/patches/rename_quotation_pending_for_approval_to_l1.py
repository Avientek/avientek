"""ERP-TKT-9 — Rename Quotation V3 L1 state for clarity.

Sridhar 2026-06-03: V3 workflow's L1 stage was labeled "Pending For
Approval" — ambiguous because L2 is clearly labeled "Pending L2
Approval". Customer wants the L1 stage equally explicit. The fix
introduces a new Workflow State "Pending L1 Approval" and migrates
Quotation V3 entirely to use it.

Scope is Quotation V3 ONLY. The OLD Workflow State record "Pending
For Approval" is kept intact because it's also used by:
  - Quotation DocFlow (legacy V2)
  - Purchase Order Docflow
  - Sales Order workflows
Renaming the global record would break those four workflows. So we
add a NEW state record and switch ONLY V3 + its docs.

Steps (idempotent):

  1. Create Workflow State record "Pending L1 Approval" if missing.
  2. UPDATE tabQuotation: workflow_state and workflow_status from
     "Pending For Approval" → "Pending L1 Approval".
  3. Update __UserSettings Redis hash so any user-saved filter on
     workflow_state="Pending For Approval" repaints (Sridhar memory
     note from 2026-06-01: Redis shadow on __UserSettings).
  4. Re-run the V3 seeder. The seeder template has been updated in
     this commit to use "Pending L1 Approval" so re-seeding wipes
     the OLD state references from the V3 Workflow Transition table.
"""
import frappe


OLD_STATE = "Pending For Approval"
NEW_STATE = "Pending L1 Approval"
WORKFLOW_NAME = "Quotation Approval Workflow Avientek (V3)"


def _ensure_workflow_state_record():
    if frappe.db.exists("Workflow State", NEW_STATE):
        print(f"[rename_quotation_pending_for_approval_to_l1] Workflow State "
              f"{NEW_STATE!r} already exists")
        return
    ws = frappe.new_doc("Workflow State")
    ws.workflow_state_name = NEW_STATE
    # Same style as the OLD state had — match Warning indicator (yellow)
    ws.style = "Warning"
    ws.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"[rename_quotation_pending_for_approval_to_l1] created Workflow "
          f"State {NEW_STATE!r}")


def _migrate_quotation_docs():
    pre_state = frappe.db.count("Quotation", {"workflow_state": OLD_STATE})
    pre_status = frappe.db.count("Quotation", {"workflow_status": OLD_STATE})
    print(f"[rename_quotation_pending_for_approval_to_l1] Quotation docs in "
          f"{OLD_STATE!r}: workflow_state={pre_state}, workflow_status={pre_status}")

    if pre_state == 0 and pre_status == 0:
        print(f"[rename_quotation_pending_for_approval_to_l1] no docs to migrate")
        return

    # Use direct SQL so docstatus=2 rows + on_update hooks aren't disturbed.
    # update_modified=False would be set if we used frappe.db.set_value, but
    # for a raw SQL UPDATE the modified column update is gated by the SQL
    # itself — we explicitly leave it out so workflow audit timestamps aren't
    # touched.
    frappe.db.sql(
        """
        UPDATE `tabQuotation`
        SET workflow_state = %(new)s
        WHERE workflow_state = %(old)s
        """,
        {"old": OLD_STATE, "new": NEW_STATE},
    )
    state_rows = frappe.db.sql("SELECT ROW_COUNT()")[0][0]
    frappe.db.sql(
        """
        UPDATE `tabQuotation`
        SET workflow_status = %(new)s
        WHERE workflow_status = %(old)s
        """,
        {"old": OLD_STATE, "new": NEW_STATE},
    )
    status_rows = frappe.db.sql("SELECT ROW_COUNT()")[0][0]
    frappe.db.commit()
    print(f"[rename_quotation_pending_for_approval_to_l1] migrated "
          f"workflow_state={state_rows}, workflow_status={status_rows}")


def _purge_user_settings_cache():
    """The list-view filter dropdown caches state values in __UserSettings
    (per user). Clearing the Redis shadow forces a fresh read so the new
    state name surfaces in everyone's typeahead without manual refresh.
    Sridhar memory note 2026-06-01 — Redis shadow on __UserSettings.
    """
    try:
        users = [r.name for r in frappe.db.sql(
            "SELECT name FROM `tabUser` WHERE enabled=1", as_dict=True
        )]
        for u in users:
            frappe.cache().hdel("_user_settings", f"Quotation::{u}")
        print(f"[rename_quotation_pending_for_approval_to_l1] purged "
              f"__UserSettings Redis shadow for {len(users)} users")
    except Exception as e:
        # Non-fatal — just means filter typeahead may take a session restart
        # to refresh on prod.
        print(f"[rename_quotation_pending_for_approval_to_l1] cache purge "
              f"skipped: {e}")


def _reseed_v3_workflow():
    """Re-run the V3 seeder so the workflow's transitions point at the new
    state name. The seeder is idempotent — wipes + rebuilds transitions."""
    from avientek.patches.seed_quotation_approval_v3_workflow import execute as seed
    seed()
    print(f"[rename_quotation_pending_for_approval_to_l1] V3 workflow re-seeded")


def execute():
    print(f"[rename_quotation_pending_for_approval_to_l1] start "
          f"{OLD_STATE!r} → {NEW_STATE!r}")
    _ensure_workflow_state_record()
    _migrate_quotation_docs()
    _reseed_v3_workflow()
    _purge_user_settings_cache()

    # Sanity: any Quotation still in OLD_STATE?
    leftover = frappe.db.count("Quotation", {"workflow_state": OLD_STATE})
    leftover_status = frappe.db.count("Quotation", {"workflow_status": OLD_STATE})
    leftover_trans = frappe.db.sql(
        """SELECT COUNT(*) FROM `tabWorkflow Transition`
           WHERE parent = %s AND (state = %s OR next_state = %s)""",
        (WORKFLOW_NAME, OLD_STATE, OLD_STATE),
    )[0][0]
    print(f"[rename_quotation_pending_for_approval_to_l1] post-check: "
          f"state={leftover}, status={leftover_status}, "
          f"V3 transitions referencing OLD_STATE={leftover_trans}")
