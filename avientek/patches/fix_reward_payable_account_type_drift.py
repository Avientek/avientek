"""Clear `account_type` on all "Reward Payable" Account docs across
companies so the Reward & Incentive JV booking stops crashing in
ERPNext's `validate_party()`.

Root cause (2026-06-17 prod error log audit): 17 Sales Invoices across
4 companies failed to book their Reward / Incentive JV between
2026-06-14 and 2026-06-16. Traceback (every failure):

    File "apps/erpnext/erpnext/accounts/doctype/journal_entry/
         journal_entry.py", line 492, in validate_party
        frappe.throw(_("Row {0}: Party Type and Party is required
                       for Receivable / Payable account {1}"))

All 9 "Reward Payable" accounts on prod have `account_type = "Payable"`
+ `root_type = Liability`. ERPNext mandates a `party_type` + `party`
on every JV credit line that posts to a Payable account.

The matching 9 "Incentive Payable" accounts have `account_type = ""`
(blank, only `root_type = Liability`) — these work today. The Reward
side is identical in intent (per-company general liability bucket for
unsettled reward obligations) but drifted to Payable, likely on a copy
from a Frappe Cloud chart template years ago.

`avientek/events/sales_invoice_reward_incentive.py:_post_jv` (file
comment at line 260) is explicit: these JV lines deliberately omit
`party_type` / `reference_type` because the reward / incentive is a
company-level liability bucket, not a per-employee subledger. Adding
a party field on the JV would require:

  - A new "Reward Earner" field on Sales Invoice (or derived from a
    Sales Person table), threading employee context through `_post_jv`.
  - Migration of historical reward data to backfill the earner.
  - Multi-company UX work (party_type can be Employee, Sales Partner,
    or Supplier depending on the company's reward program).

Out of scope. The intended design (per the existing code comment) is
a generic liability bucket — match Incentive Payable's `account_type=""`
config and let validate_party pass through.

Idempotent: only writes to accounts where `account_type != ""`. Logs
each touch.
"""

import frappe


_ACCOUNT_TYPE_FIELD = "account_type"
_TARGET_VALUE = ""


def execute():
    rows = frappe.db.sql(
        """
        SELECT name, company, account_type
        FROM `tabAccount`
        WHERE name LIKE %s
          AND account_type != ''
          AND is_group = 0
        """,
        ("%Reward Payable%",),
        as_dict=True,
    )

    if not rows:
        print(
            "fix_reward_payable_account_type_drift: no accounts need "
            "updating (account_type already blank on all Reward Payable "
            "accounts)"
        )
        return

    for r in rows:
        frappe.db.set_value(
            "Account",
            r["name"],
            _ACCOUNT_TYPE_FIELD,
            _TARGET_VALUE,
            update_modified=False,
        )
        print(
            f"fix_reward_payable_account_type_drift: cleared "
            f"account_type ({r['account_type']!r} → '') on "
            f"{r['name']} ({r['company']})"
        )

    frappe.db.commit()
    print(
        f"fix_reward_payable_account_type_drift: updated {len(rows)} "
        f"account(s). Existing booked JVs unaffected."
    )
