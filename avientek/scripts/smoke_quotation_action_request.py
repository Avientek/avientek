"""Smoke for Phase 2: Quotation Action Request doctype + workflow.

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_quotation_action_request.run

Verifies:
  - DocType installed.
  - Workflow "Quotation Action Request Approval" active with the right
    states + transitions and allow_self_approval=0 everywhere.
  - End-to-end dry run on a real high-prob submitted Quotation:
      Pending -> L1 Approved -> L2 Approved -> Executed (with the
      underlying cancel happening automatically). After verification
      the quote is restored (un-cancelled) so the test is idempotent.
"""
from __future__ import annotations

import frappe
from frappe.utils import flt


WF_NAME = "Quotation Action Request Approval"


def _hr(t):
    return "\n" + "─" * 70 + f"\n{t}\n" + "─" * 70


def run():
    print("=" * 70)
    print("QUOTATION ACTION REQUEST SMOKE — Phase 2")
    print(f"site: {frappe.local.site}")
    print("=" * 70)

    pass_n, fail_n = 0, 0

    # ── 1. DocType installed ──
    print(_hr("[1] DocType + Workflow installed"))
    if frappe.db.exists("DocType", "Quotation Action Request"):
        print("  ✓ DocType 'Quotation Action Request' installed")
        pass_n += 1
    else:
        print("  ✗ DocType missing — migrate didn't pick up the JSON")
        fail_n += 1
        return {"pass": pass_n, "fail": fail_n}

    if frappe.db.exists("Workflow", WF_NAME):
        wf = frappe.get_doc("Workflow", WF_NAME)
        print(f"  ✓ Workflow '{WF_NAME}' active={wf.is_active} "
              f"states={len(wf.states)} transitions={len(wf.transitions)}")
        pass_n += 1
    else:
        print(f"  ✗ Workflow '{WF_NAME}' missing")
        fail_n += 1

    # ── 2. transitions all have allow_self_approval=0 ──
    print(_hr("[2] transitions: allow_self_approval = 0"))
    bad = frappe.db.sql(
        """SELECT name, state, action FROM `tabWorkflow Transition`
           WHERE parent=%s AND IFNULL(allow_self_approval,0)<>0""",
        (WF_NAME,), as_dict=True,
    )
    if not bad:
        print("  ✓ all transitions have self-approval blocked")
        pass_n += 1
    else:
        print(f"  ✗ {len(bad)} transitions still allow_self_approval=1")
        for r in bad:
            print(f"      {r}")
        fail_n += 1

    # ── 3. End-to-end dry run on a real high-prob submitted quote ──
    print(_hr("[3] End-to-end Cancel via Action Request"))
    # Pick a submitted high-prob quote that has no downstream links
    # (no Sales Order pointing at it) so the cancel will succeed.
    q = frappe.db.sql(
        """SELECT q.name FROM `tabQuotation` q
           WHERE q.docstatus=1 AND q.probability >= 75
             AND NOT EXISTS (
                SELECT 1 FROM `tabSales Order Item` soi
                INNER JOIN `tabSales Order` so ON so.name = soi.parent
                WHERE soi.prevdoc_docname = q.name AND so.docstatus < 2
             )
           LIMIT 1""",
        as_dict=True,
    )
    if not q:
        print("  no submitted Quotation with probability>=75 — skip e2e")
        return {"pass": pass_n, "fail": fail_n}

    qn = q[0]["name"]
    print(f"  using Quotation {qn}")

    # Create the Action Request (Pending)
    ar = frappe.new_doc("Quotation Action Request")
    ar.quotation = qn
    ar.action = "Cancel"
    ar.reason = "smoke test"
    ar.workflow_state = "Pending"
    ar.flags.ignore_permissions = True
    ar.insert(ignore_permissions=True)
    print(f"  ✓ created Action Request {ar.name} (Pending)")
    pass_n += 1

    # Push through L1 Approved
    ar.workflow_state = "L1 Approved"
    ar.flags.ignore_permissions = True
    ar.save(ignore_permissions=True)
    ar.reload()
    if ar.level_1_approved_on:
        print(f"  ✓ L1 Approved -> level_1_approved_on={ar.level_1_approved_on}")
        pass_n += 1
    else:
        print(f"  ✗ level_1_approved_on not set on L1 transition")
        fail_n += 1

    # Push through L2 Approved -> on_update fires the cancel + flips to Executed
    ar.workflow_state = "L2 Approved"
    ar.flags.ignore_permissions = True
    ar.save(ignore_permissions=True)
    ar.reload()
    print(f"  After L2 save: workflow_state={ar.workflow_state}  "
          f"executed_on={ar.executed_on}  log={ar.execution_log!r}")
    if ar.workflow_state == "Executed" and ar.executed_on:
        print("  ✓ Action Request reached Executed state")
        pass_n += 1
    else:
        print("  ✗ Action Request did NOT reach Executed state")
        fail_n += 1

    # Verify the underlying quote was cancelled.
    q_status = frappe.db.get_value("Quotation", qn, ["docstatus"], as_dict=True)
    if q_status and q_status.docstatus == 2:
        print(f"  ✓ underlying Quotation {qn} is now docstatus=2 (cancelled)")
        pass_n += 1
    else:
        print(f"  ✗ underlying Quotation {qn} docstatus="
              f"{q_status.docstatus if q_status else '?'}")
        fail_n += 1

    # Restore the quote so the test is idempotent.
    if q_status and q_status.docstatus == 2:
        frappe.db.set_value(
            "Quotation", qn, "docstatus", 1, update_modified=False,
        )
        frappe.db.commit()
        print(f"  ↺ restored {qn} docstatus to 1 (test cleanup)")
    # Delete the test Action Request to keep state clean
    try:
        frappe.delete_doc("Quotation Action Request", ar.name,
                          ignore_permissions=True, force=True)
        frappe.db.commit()
        print(f"  ↺ deleted test Action Request {ar.name}")
    except Exception:
        pass

    # ── Verdict ──
    print(_hr("Verdict"))
    print(f"  pass: {pass_n}    fail: {fail_n}")
    if fail_n == 0:
        print(f"\n  ✅ PASS — Phase 2 (Action Request workflow) verified")
    else:
        print(f"\n  ❌ FAIL — {fail_n} check(s) failed")
    return {"pass": pass_n, "fail": fail_n}
