"""Block self-approval on the Payment Request Form Approval workflow.

Sridhar 2026-05-06: "workflow authorization is incorrectly configured,
allowing the user who created the payment request to authorize it".

Root cause
----------
Every transition on the active `Payment Request Form Approval` workflow
has `allow_self_approval=1`. When that flag is set, Frappe lets the
same user who saved/submitted the doc fire the transition — defeating
the multi-level approval chain (Authorise → Approve L1 → Approve L2
→ Release).

Fix
---
Sets `allow_self_approval = 0` on every transition of every workflow
whose `document_type = 'Payment Request Form'`. Idempotent: re-running
just keeps everything at 0.

Wired into both `patches.txt` (one-shot retroactive fix on first
migrate after deploy) AND `after_migrate` (defensive — re-asserts
every migrate so any UI re-edit that flips it back to 1 gets
overridden on the next deploy).
"""
import frappe


def execute():
    return enforce_no_self_approval()


def enforce_no_self_approval():
    """Set allow_self_approval=0 on every PRF workflow transition.

    Returns dict with counts for verification."""
    rows = frappe.db.sql(
        """SELECT t.name, t.parent, t.state, t.action, t.allowed,
                  t.allow_self_approval
           FROM `tabWorkflow Transition` t
           INNER JOIN `tabWorkflow` w ON w.name = t.parent
           WHERE w.document_type = 'Payment Request Form'""",
        as_dict=True,
    )
    if not rows:
        print("[block_prf_workflow_self_approval] no PRF workflow transitions")
        return {"updated": 0, "already_clean": 0}

    to_fix = [r for r in rows if (r.get("allow_self_approval") or 0)]
    already = len(rows) - len(to_fix)

    for r in to_fix:
        frappe.db.set_value(
            "Workflow Transition", r["name"],
            "allow_self_approval", 0, update_modified=False,
        )

    if to_fix:
        # Bust workflow caches so the change is picked up on the next
        # transition request without a server restart.
        for parent_name in {r["parent"] for r in to_fix}:
            try:
                frappe.clear_document_cache("Workflow", parent_name)
            except Exception:
                pass
        frappe.db.commit()

    print(
        f"[block_prf_workflow_self_approval] "
        f"workflows={len({r['parent'] for r in rows})} "
        f"transitions={len(rows)} updated={len(to_fix)} "
        f"already_clean={already}"
    )
    return {"updated": len(to_fix), "already_clean": already}
