# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
#
# Jithin 2026-05-15 — clean up Quotations that bypassed the V3 margin
# approval gate.
#
# Background: after deploying the V3 Quotation workflow on 2026-05-09,
# a gap in the seeder allowed sales users to click *Submit* on quotes
# where `set_margin_flags` had already computed
# `custom_auto_approve_ok = 0` (margin requires L1/L2 approval).
# QN-LTD-26-02011 (-1.52% margin vs 6% brand standard) was the example
# Jithin flagged on WhatsApp; a quick audit on 2026-05-15 found ~17
# similarly leaked quotes.
#
# This patch:
#   1. AUTO-FIX — every leaked quote currently at workflow_state =
#      'Submitted' is re-routed back to 'Pending For Approval'
#      (docstatus=0, status='Draft') so it picks up the corrected
#      approval flow on next save. Safe because Submitted-state quotes
#      have no downstream Sales Order / Invoice commitments.
#
#   2. LOG-ONLY — every leaked quote at 'Approved' is listed for
#      manual review. These have likely been converted to Sales
#      Orders / Invoices already, so the accounts / sales-ops team has
#      to decide case-by-case how to handle them (cancel + amend,
#      retroactive approval note, or leave as-is depending on
#      downstream commitments).
#
# Idempotent: re-running only touches rows that still match the leak
# signature (workflow_state='Submitted' AND
# custom_auto_approve_ok=0 AND creation >= 2026-05-09). After the
# first run those rows move to 'Pending For Approval' and stop
# matching.

import frappe

# V3 workflow was deployed on this date — anything before this fell
# under the legacy V2 workflow, which had its own (working) margin gate.
V3_DEPLOY_DATE = "2026-05-09"


def execute():
    _fix_submitted_leaks()
    _log_approved_leaks()


def _fix_submitted_leaks():
    rows = frappe.db.sql(
        """SELECT name FROM `tabQuotation`
           WHERE docstatus = 1
             AND workflow_state = 'Submitted'
             AND IFNULL(custom_auto_approve_ok, 0) = 0
             AND creation >= %s""",
        (V3_DEPLOY_DATE,),
    )
    names = [r[0] for r in rows]
    if not names:
        print("[fix_post_v3_quotation_margin_leaks] no Submitted-state leaks to fix")
        return

    frappe.db.sql(
        """UPDATE `tabQuotation`
           SET docstatus = 0,
               workflow_state = 'Pending For Approval',
               status = 'Draft'
           WHERE docstatus = 1
             AND workflow_state = 'Submitted'
             AND IFNULL(custom_auto_approve_ok, 0) = 0
             AND creation >= %s""",
        (V3_DEPLOY_DATE,),
    )
    frappe.db.commit()
    print(
        f"[fix_post_v3_quotation_margin_leaks] re-routed {len(names)} Submitted-state "
        f"leaks to Pending For Approval (docstatus=0, status=Draft): {', '.join(names)}"
    )


def _log_approved_leaks():
    rows = frappe.db.sql(
        """SELECT name, company, party_name, creation, owner
           FROM `tabQuotation`
           WHERE docstatus = 1
             AND workflow_state = 'Approved'
             AND IFNULL(custom_auto_approve_ok, 0) = 0
             AND creation >= %s
           ORDER BY creation DESC""",
        (V3_DEPLOY_DATE,),
        as_dict=True,
    )
    if not rows:
        print("[fix_post_v3_quotation_margin_leaks] no Approved-state leaks to log")
        return

    print(
        f"[fix_post_v3_quotation_margin_leaks] {len(rows)} Approved-state leaks "
        f"REQUIRE MANUAL REVIEW (likely have linked Sales Orders / Invoices):"
    )
    for r in rows:
        print(
            f"    - {r['name']} | {r['company']} | {r['party_name']} | "
            f"created {r['creation']} by {r['owner']}"
        )
