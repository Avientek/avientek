"""Drop the Quotation Action Request DocType + workflow on existing
sites (Rahul/Sridhar 2026-05-08 — replaced by SO-style Document Approval
pattern on Quotation itself).

Idempotent. Safe to re-run. Removes:
  - Workflow record `Quotation Action Request Approval`
  - Workflow Transition rows for that workflow
  - Workflow Action Master rows `Approve L1` / `Approve L2` (only if no
    other Workflow references them)
  - Workflow State rows `Pending` / `L1 Approved` / `L2 Approved` /
    `Executed` (only if no other Workflow references them)
  - tabQuotation Action Request data table + DocType row

Does NOT touch:
  - `Quotation Approval Workflow Avientek (V3)` (the new approval flow)
  - `Avientek Quotation Restricted Role` child doctype (still drives RBAC)
  - High-prob lock validators
  - Avientek Settings high-prob role config (handled separately by
    Phase 1 fixture changes)
"""
import frappe


WORKFLOW_NAME = "Quotation Action Request Approval"
DOCTYPE_NAME = "Quotation Action Request"
QAR_ONLY_ACTIONS = ["Approve L1", "Approve L2"]
QAR_ONLY_STATES = ["L1 Approved", "L2 Approved", "Executed"]
# Pending / Rejected may be shared with other workflows — leave them.


def execute():
    return run()


def _action_used_elsewhere(action_name):
    return bool(frappe.db.count(
        "Workflow Transition",
        {"action": action_name, "parent": ["!=", WORKFLOW_NAME]},
    ))


def _state_used_elsewhere(state_name):
    return bool(
        frappe.db.count(
            "Workflow Document State",
            {"state": state_name, "parent": ["!=", WORKFLOW_NAME]},
        )
        or frappe.db.count(
            "Workflow Transition",
            {"next_state": state_name, "parent": ["!=", WORKFLOW_NAME]},
        )
    )


def run():
    summary = []

    # 1. Drop the Workflow (cascades to Workflow Transition + Workflow Document State).
    if frappe.db.exists("Workflow", WORKFLOW_NAME):
        try:
            frappe.delete_doc("Workflow", WORKFLOW_NAME, force=1, ignore_permissions=True)
            summary.append(f"deleted Workflow {WORKFLOW_NAME!r}")
        except Exception as e:
            summary.append(f"WARN failed to delete Workflow: {e!r}")
    else:
        summary.append(f"Workflow {WORKFLOW_NAME!r} already absent")

    # 2. Drop QAR-only Workflow Action Master rows.
    for action in QAR_ONLY_ACTIONS:
        if not frappe.db.exists("Workflow Action Master", action):
            continue
        if _action_used_elsewhere(action):
            summary.append(f"Workflow Action Master {action!r} retained (used elsewhere)")
            continue
        try:
            frappe.delete_doc("Workflow Action Master", action, force=1, ignore_permissions=True)
            summary.append(f"deleted Workflow Action Master {action!r}")
        except Exception as e:
            summary.append(f"WARN failed to delete Action Master {action!r}: {e!r}")

    # 3. Drop QAR-only Workflow State rows.
    for state in QAR_ONLY_STATES:
        if not frappe.db.exists("Workflow State", state):
            continue
        if _state_used_elsewhere(state):
            summary.append(f"Workflow State {state!r} retained (used elsewhere)")
            continue
        try:
            frappe.delete_doc("Workflow State", state, force=1, ignore_permissions=True)
            summary.append(f"deleted Workflow State {state!r}")
        except Exception as e:
            summary.append(f"WARN failed to delete State {state!r}: {e!r}")

    # 4. Drop QAR data + DocType.
    if frappe.db.exists("DocType", DOCTYPE_NAME):
        # Wipe data first to avoid orphan rows.
        try:
            frappe.db.sql("DELETE FROM `tabQuotation Action Request`")
            summary.append("wiped tabQuotation Action Request rows")
        except Exception:
            pass
        try:
            frappe.delete_doc("DocType", DOCTYPE_NAME, force=1, ignore_permissions=True)
            summary.append(f"deleted DocType {DOCTYPE_NAME!r}")
        except Exception as e:
            summary.append(f"WARN failed to delete DocType: {e!r}")
        # Drop residual table if Frappe didn't.
        try:
            frappe.db.sql("DROP TABLE IF EXISTS `tabQuotation Action Request`")
        except Exception:
            pass
    else:
        summary.append(f"DocType {DOCTYPE_NAME!r} already absent")

    # 5. Drop Patch Log rows for the old QAR seeder so re-running migrate
    #    doesn't try to import the deleted module.
    try:
        frappe.db.sql(
            """DELETE FROM `tabPatch Log`
               WHERE patch LIKE '%seed_quotation_action_request_workflow%'"""
        )
        summary.append("cleared seed_quotation_action_request_workflow Patch Log")
    except Exception:
        pass

    frappe.db.commit()
    print("[remove_quotation_action_request]")
    for s in summary:
        print(f"  {s}")
    return summary
