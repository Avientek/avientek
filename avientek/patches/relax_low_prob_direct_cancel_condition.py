# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Rahul 2026-08-10 (WhatsApp): "quote with 75% below is not able to cancel by
# the user, from today." The direct (single-click) Cancel from Approved was
# gated on `doc.custom_auto_approve_ok == 1` (margin up to mark), so any
# low-probability (<75%) quote whose margin was below mark had NO Cancel
# button and was forced through the Request Cancellation -> L1 -> L2 chain.
#
# Business decision (Rahul 2026-08-10): ANY <75% quote must be directly
# cancellable by the creator / L1 / L2, regardless of margin. High-probability
# quotes still route through the cancellation chain (the probability filter in
# the condition below excludes them from direct cancel).
#
# The seeder (seed_quotation_approval_v3_workflow.py) already carries the
# relaxed DIRECT_CANCEL_COND, but that seeder is CREATE-ONLY since PR #21 — it
# no longer re-applies to an existing Workflow. This patch surgically rewrites
# ONLY the `Approved -> Cancel` transition condition on the live workflow,
# leaving every other transition (and the UI self-approval flags) untouched.
# Idempotent: once rewritten the rows no longer match, so re-runs are no-ops.

import frappe

WORKFLOW = "Quotation Approval Workflow Avientek (V3)"

# Must stay byte-identical to CANCEL_COND in seed_quotation_approval_v3_workflow.py
RELAXED_COND = (
    "(doc.probability or 0) < 75 and doc.probabilities not in "
    "('75%', '80%', '85%', '90%', '95%', '100%')"
)


def execute():
    if not frappe.db.exists("Workflow", WORKFLOW):
        return

    rows = frappe.get_all(
        "Workflow Transition",
        filters={"parent": WORKFLOW, "state": "Approved", "action": "Cancel"},
        fields=["name", "condition"],
    )

    updated = 0
    for r in rows:
        if r.condition and "custom_auto_approve_ok" in r.condition:
            frappe.db.set_value(
                "Workflow Transition", r.name, "condition", RELAXED_COND,
                update_modified=False,
            )
            updated += 1

    if updated:
        frappe.clear_document_cache("Workflow", WORKFLOW)
        print(
            f"[relax_low_prob_direct_cancel] relaxed {updated} Approved->Cancel "
            f"transition condition(s) — <75% quotes now directly cancellable "
            f"regardless of margin"
        )
