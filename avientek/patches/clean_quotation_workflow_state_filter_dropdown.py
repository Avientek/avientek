"""ERP-TKT-11 — Clean duplicate / stale entries from the Quotation
workflow_state filter dropdown.

Sridhar 2026-06-04 ticket: "Workflow state duplicate in Filter".
After TKT-9 (Pending For Approval → Pending L1 Approval rename) and
TKT-10 (Pending Level 2 Approval → Pending L2 Approval normalization),
the list-view filter dropdown still showed:
  - "Pending For Approval"     (deprecated by TKT-9)
  - "Pending Level 1 Approval" (V2 legacy)
  - "Pending Level 2 Approval" (V2 legacy, deprecated by TKT-10)
AND was missing the new V3 canonical "Pending L1 Approval". The
dropdown is driven by a `link_filters` setting on the Quotation
Custom Field workflow_state (mirror field workflow_status has the
same setting).

Pre-fix `link_filters` value (14 states):
  Approved, Approved for Update, Cancellation L2 Pending,
  Cancellation Requested, Cancelled, Draft, Pending For Approval,
  Pending L2 Approval, Pending Level 1 Approval,
  Pending Level 2 Approval, Rejected, Requested for update,
  Sent for Revision, Submitted

Post-fix (12 states — V3 canonical only):
  Approved, Approved for Update, Cancellation L2 Pending,
  Cancellation Requested, Cancelled, Draft,
  Pending L1 Approval, Pending L2 Approval,
  Rejected, Requested for update, Sent for Revision, Submitted

Also migrates the 1 remaining Quotation doc still in legacy
'Pending Level 1 Approval' → 'Pending L1 Approval'. (TKT-10 already
cleaned the L2 equivalent; this finishes the L1 side.)

Idempotent.
"""
import json
import frappe


# Canonical V3 dropdown set (matches the active V3 workflow's state list,
# excluding the V2 bridge entries that the workflow keeps for safety
# in case any unmigrated doc surfaces).
CANONICAL_STATES = [
    "Approved",
    "Approved for Update",
    "Cancellation L2 Pending",
    "Cancellation Requested",
    "Cancelled",
    "Draft",
    "Pending L1 Approval",
    "Pending L2 Approval",
    "Rejected",
    "Requested for update",
    "Sent for Revision",
    "Submitted",
]

LEGACY_L1 = "Pending Level 1 Approval"
NEW_L1 = "Pending L1 Approval"


def _update_link_filters():
    new_filters = json.dumps(
        [["Workflow State", "name", "in", CANONICAL_STATES]],
        separators=(", ", ": "),
    )
    cf_names = ["Quotation-workflow_state", "Quotation-workflow_status"]
    for cf in cf_names:
        if not frappe.db.exists("Custom Field", cf):
            print(f"[clean_quotation_workflow_state_filter_dropdown] missing {cf} — skip")
            continue
        cur = frappe.db.get_value("Custom Field", cf, "link_filters")
        if cur == new_filters:
            print(f"[clean_quotation_workflow_state_filter_dropdown] {cf} link_filters already clean")
            continue
        frappe.db.set_value("Custom Field", cf, "link_filters", new_filters,
                            update_modified=False)
        print(f"[clean_quotation_workflow_state_filter_dropdown] updated {cf} link_filters "
              f"({len(CANONICAL_STATES)} states)")


def _migrate_remaining_l1_legacy():
    cnt_state = frappe.db.count("Quotation", {"workflow_state": LEGACY_L1})
    cnt_status = frappe.db.count("Quotation", {"workflow_status": LEGACY_L1})
    if cnt_state == 0 and cnt_status == 0:
        print(f"[clean_quotation_workflow_state_filter_dropdown] no remaining "
              f"{LEGACY_L1!r} docs to migrate")
        return
    print(f"[clean_quotation_workflow_state_filter_dropdown] migrating "
          f"{cnt_state} state + {cnt_status} status rows {LEGACY_L1!r} → {NEW_L1!r}")
    frappe.db.sql(
        "UPDATE `tabQuotation` SET workflow_state = %(new)s WHERE workflow_state = %(old)s",
        {"old": LEGACY_L1, "new": NEW_L1},
    )
    frappe.db.sql(
        "UPDATE `tabQuotation` SET workflow_status = %(new)s WHERE workflow_status = %(old)s",
        {"old": LEGACY_L1, "new": NEW_L1},
    )


def _purge_user_settings_cache():
    """The list-view filter dropdown caches state values in __UserSettings
    (per user) in Redis. Without purge, users see stale options until they
    log out + back in. (Sridhar memory: __UserSettings is Redis-shadowed.)
    """
    try:
        users = [r.name for r in frappe.db.sql(
            "SELECT name FROM `tabUser` WHERE enabled=1", as_dict=True
        )]
        for u in users:
            frappe.cache().hdel("_user_settings", f"Quotation::{u}")
        print(f"[clean_quotation_workflow_state_filter_dropdown] purged "
              f"__UserSettings for {len(users)} users")
    except Exception as e:
        print(f"[clean_quotation_workflow_state_filter_dropdown] cache "
              f"purge skipped: {e}")


def execute():
    _migrate_remaining_l1_legacy()
    _update_link_filters()
    frappe.db.commit()
    frappe.clear_cache(doctype="Quotation")
    _purge_user_settings_cache()
    print(f"[clean_quotation_workflow_state_filter_dropdown] done")
