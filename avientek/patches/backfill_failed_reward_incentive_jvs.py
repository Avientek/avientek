"""Backfill Reward & Incentive JVs for Sales Invoices whose on_submit
JV booking failed between 2026-06-14 and 2026-06-16.

These SIs submitted cleanly (revenue and customer receivable posted)
but `book_reward_incentive_jv` crashed inside ERPNext's
`validate_party()` because the Reward Payable accounts were configured
`account_type = "Payable"` (which mandates party_type/party on the
JV row). The same root cause is fixed by
`fix_reward_payable_account_type_drift` (runs before this patch).

Because the on_submit hook is wrapped in try/except + frappe.log_error,
the SI submit succeeded but no Reward / Incentive JV was posted. The
custom field `custom_reward_incentive_jv` was never stamped on these
SIs — which makes them safely backfillable via the same hook
(idempotency check at sales_invoice_reward_incentive.py:59).

Strategy:
  1. Query Error Log for `Reward Incentive JV booking failed for *`
     entries since 2026-06-14.
  2. Extract SI name from the method (e.g.
     "Reward Incentive JV booking failed for LTD-26-27-00418").
  3. For each unique SI, skip if cancelled OR already has a JV stamped.
  4. Re-load and re-invoke `book_reward_incentive_jv(doc, method=None)`.

Idempotent: each SI is skipped if it already has a JV (the hook's own
existence check handles this).

Self-healing: any SI that still fails (e.g. a future SI where the
account_type drifted again) logs a fresh Error Log, which surfaces in
the next audit.
"""

import re

import frappe

from avientek.events.sales_invoice_reward_incentive import (
    book_reward_incentive_jv,
)


_SI_NAME_RE = re.compile(
    r"^Reward Incentive JV booking failed for (?P<name>[A-Za-z0-9_\-]+)$"
)
_BACKFILL_FROM_DATE = "2026-06-14 00:00:00"


def execute():
    rows = frappe.db.sql(
        """
        SELECT DISTINCT method
        FROM `tabError Log`
        WHERE method LIKE 'Reward Incentive JV booking failed for %%'
          AND creation >= %s
        """,
        (_BACKFILL_FROM_DATE,),
        as_dict=True,
    )

    si_names = []
    for r in rows:
        m = _SI_NAME_RE.match((r["method"] or "").strip())
        if m:
            si_names.append(m.group("name"))

    if not si_names:
        print("backfill_failed_reward_incentive_jvs: nothing to backfill")
        return

    succeeded = 0
    skipped_cancelled = 0
    skipped_already = 0
    failed = 0

    for si_name in sorted(set(si_names)):
        if not frappe.db.exists("Sales Invoice", si_name):
            print(f"  SKIP {si_name}: no longer exists")
            continue

        doc = frappe.get_doc("Sales Invoice", si_name)
        if doc.docstatus != 1:
            skipped_cancelled += 1
            print(f"  SKIP {si_name}: docstatus={doc.docstatus} (not submitted)")
            continue

        if doc.get("custom_reward_incentive_jv"):
            skipped_already += 1
            print(
                f"  SKIP {si_name}: already linked to JV "
                f"{doc.get('custom_reward_incentive_jv')}"
            )
            continue

        try:
            book_reward_incentive_jv(doc, method=None)
            doc.reload()
            jv = doc.get("custom_reward_incentive_jv")
            if jv:
                succeeded += 1
                print(f"  OK   {si_name}: booked JV {jv}")
            else:
                # hook returned without stamping — likely skipped at one
                # of the early returns (no quote / zero amounts / no
                # settings for company). Not a failure; just no JV due.
                print(f"  NOOP {si_name}: hook skipped (no JV due)")
        except Exception:
            failed += 1
            print(f"  FAIL {si_name}: see Error Log")
            frappe.log_error(
                title=f"backfill_failed_reward_incentive_jvs: {si_name}",
                message=frappe.get_traceback(),
            )

    frappe.db.commit()
    print(
        f"backfill_failed_reward_incentive_jvs: "
        f"succeeded={succeeded}, skipped_cancelled={skipped_cancelled}, "
        f"skipped_already={skipped_already}, failed={failed}, "
        f"total={len(set(si_names))}"
    )
