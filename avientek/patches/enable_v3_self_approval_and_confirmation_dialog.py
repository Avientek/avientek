"""Sridhar/Rahul 2026-06-10 — on the V3 Quotation Approval Workflow:

  1. Enable "Allow Self Approval" on EVERY transition row. On local
     16 of 37 transitions had it unchecked; the user wants the same
     UX as the others (creator can pass their own quote through if
     they hold the required role).
  2. Enable the workflow-header "Enable Confirmation Dialog" toggle
     (Avientek Custom Field `custom_enable_confirmation`) so Frappe
     pops a confirmation modal before each workflow action.

Scope is intentionally NARROW — only the active V3 workflow
("Quotation Approval Workflow Avientek (V3)"). PRF and other
workflows are untouched (Jithin's earlier patch
block_prf_workflow_self_approval relied on PRF transitions having
allow_self_approval=0 — that guard stays in place).

Idempotent. Re-runs are no-ops once everything is set.
"""
import frappe


WORKFLOW_NAME = "Quotation Approval Workflow Avientek (V3)"


def _enable_confirmation_dialog():
    if not frappe.db.exists("Workflow", WORKFLOW_NAME):
        print(f"[enable_v3_self_approval_and_confirmation_dialog] {WORKFLOW_NAME!r} missing — skip")
        return False
    cur = frappe.db.get_value("Workflow", WORKFLOW_NAME, "custom_enable_confirmation")
    if cur == 1:
        print(f"[enable_v3_self_approval_and_confirmation_dialog] custom_enable_confirmation already 1")
        return False
    frappe.db.set_value(
        "Workflow", WORKFLOW_NAME,
        "custom_enable_confirmation", 1,
        update_modified=False,
    )
    print(f"[enable_v3_self_approval_and_confirmation_dialog] "
          f"custom_enable_confirmation set 1 (was {cur!r})")
    return True


def _enable_self_approval_on_all_transitions():
    """Flip allow_self_approval=1 on every Workflow Transition row whose
    `parent` is the V3 workflow. Direct UPDATE is the right call here:
    Workflow Transition has no on-change side effects, and
    frappe.db.set_value would loop 37 times for the same effect.
    """
    rows_before = frappe.db.sql(
        """
        SELECT name, state, action, allow_self_approval
        FROM `tabWorkflow Transition`
        WHERE parent=%s AND parenttype='Workflow'
        """,
        (WORKFLOW_NAME,),
        as_dict=True,
    )
    missing = [r for r in rows_before if not r.allow_self_approval]
    if not missing:
        print(f"[enable_v3_self_approval_and_confirmation_dialog] all "
              f"{len(rows_before)} transitions already have allow_self_approval=1")
        return False
    affected = frappe.db.sql(
        """
        UPDATE `tabWorkflow Transition`
        SET allow_self_approval=1
        WHERE parent=%s AND parenttype='Workflow'
          AND (allow_self_approval IS NULL OR allow_self_approval=0)
        """,
        (WORKFLOW_NAME,),
    )
    print(f"[enable_v3_self_approval_and_confirmation_dialog] "
          f"set allow_self_approval=1 on {len(missing)} of {len(rows_before)} "
          f"transitions (rest already 1)")
    return True


def _clear_workflow_cache():
    try:
        frappe.clear_cache(doctype="Quotation")
        # Workflow doctype itself also caches its in-memory rep
        frappe.clear_document_cache("Workflow", WORKFLOW_NAME)
        print(f"[enable_v3_self_approval_and_confirmation_dialog] cleared workflow + Quotation cache")
    except Exception as e:
        print(f"[enable_v3_self_approval_and_confirmation_dialog] cache clear note: {e}")


def execute():
    changed_a = _enable_confirmation_dialog()
    changed_b = _enable_self_approval_on_all_transitions()
    if changed_a or changed_b:
        frappe.db.commit()
        _clear_workflow_cache()
    print(f"[enable_v3_self_approval_and_confirmation_dialog] done")
