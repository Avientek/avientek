"""Bridge patch — re-run the V3 Quotation Approval workflow seeder so
existing sites pick up the new "Approve" transition.

Sridhar/Rahul/Jithin ERP-TKT-2 2026-06-05 — second-pass refinement to
the incentive routing. Jithin clarified on WhatsApp that L1 should be
able to either approve OR escalate after reviewing/editing the quote,
not just escalate. The V3 workflow had only one transition out of
"Pending For Approval" (→ Pending L2 Approval, unconditional), forcing
every approval to bounce to L2.

The seeder template (seed_quotation_approval_v3_workflow.py) was
updated to add a new transition:

  ("Pending For Approval", "Approve", "Approved", "l1_approver", 1,
   "doc.custom_level_1_approve_ok == 1")

The existing escalation ("Approve Level 1" → Pending L2 Approval)
stays as-is so L1 can always choose to escalate.

Since patches.txt entries only run once per site (memory:
feedback-patches-txt-seeders-once-only), this bridge patch re-runs the
seeder so live sites get the new transition without a re-install.
The seeder itself is fully idempotent — wf.set("transitions", []) +
re-append wipes and rebuilds — so re-running is safe.

After this patch:
  - L1 reviewer in "Pending For Approval":
    * If flags = (0, 1) → both buttons visible: "Approve" (to Approved)
      and "Approve Level 1" (escalate to Pending L2 Approval)
    * If flags = (0, 0) → only "Approve Level 1" visible (must escalate)
    * After L1 edits + saves, set_margin_flags re-runs and flags update;
      buttons re-render to match the new state.
"""
import frappe


def execute():
    print("[add_l1_direct_approve_v3] re-running V3 workflow seeder for L1 direct-approve")
    from avientek.patches.seed_quotation_approval_v3_workflow import execute as seed
    seed()
    print("[add_l1_direct_approve_v3] done")
