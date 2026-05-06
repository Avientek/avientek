"""Inspect PRF workflow for the self-authorization issue Sridhar flagged
2026-05-06: 'workflow authorization is incorrectly configured, allowing
the user who created the payment request to authorize it'.

Frappe Workflow has `Workflow Transition.allow_self_approval` (Check).
When 1, the same user who saved/submitted the doc can also fire the
transition. When 0, Frappe blocks self-approval.

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.diag_prf_workflow.run
"""
import frappe


def run():
    print("=" * 70)
    print("PRF WORKFLOW DIAGNOSTIC")
    print("=" * 70)
    wfs = frappe.db.sql(
        """SELECT name, is_active, send_email_alert, override_status
           FROM `tabWorkflow`
           WHERE document_type = 'Payment Request Form'
           ORDER BY is_active DESC""", as_dict=True,
    )
    if not wfs:
        print("  no Payment Request Form workflow on this site")
        return
    for w in wfs:
        print(f"\nWorkflow: {w['name']}  active={w['is_active']}")
        states = frappe.db.sql(
            """SELECT state, doc_status, allow_edit, update_field, update_value
               FROM `tabWorkflow Document State`
               WHERE parent = %s ORDER BY idx""",
            (w["name"],), as_dict=True,
        )
        print(f"  states: {len(states)}")
        for s in states:
            print(f"    {s['state']:30s} ds={s['doc_status']} "
                  f"edit_role='{s['allow_edit']}' "
                  f"update_field={s['update_field']!r}")
        trs = frappe.db.sql(
            """SELECT state, action, next_state, allowed, allow_self_approval,
                      `condition`
               FROM `tabWorkflow Transition`
               WHERE parent = %s ORDER BY idx""",
            (w["name"],), as_dict=True,
        )
        print(f"  transitions: {len(trs)}")
        any_self = False
        for t in trs:
            self_flag = int(t['allow_self_approval'] or 0)
            if self_flag:
                any_self = True
            mark = " ★ SELF=1" if self_flag else ""
            cond = f" if [{t['condition']}]" if t['condition'] else ""
            print(f"    {t['state']:25s} -[{t['action']:20s}]-> "
                  f"{t['next_state']:25s}  role='{t['allowed']}'{mark}{cond}")
        if any_self:
            print(f"\n  ⚠ FOUND: at least one transition has "
                  f"allow_self_approval=1 — fix is to set it to 0.")
        else:
            print(f"\n  No allow_self_approval=1 transitions found. "
                  f"If self-approval still happens, the bug is elsewhere "
                  f"(role assignment overlap or absent transition guards).")
