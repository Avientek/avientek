"""One-time Error Log purge — delete rows older than 24 hours.

Companion to the 2026-06-17 production-ready sweep. After the
following fixes ship:

  - `fix_reward_payable_account_type_drift` (Reward JV unblock)
  - `backfill_failed_reward_incentive_jvs` (retry the 17 failed SIs)
  - quotation_notifications._assign_todo gets ignore_permissions=True
    (kills 73 prod log spams / week)
  - deploy of master tip 3f7fad5 also lands:
      f07c158 — block_print_unless_approved arg-count fix (19 prod fails)
      a248eda — Quote per-item tax fix

…the legacy backlog of Error Log rows attributable to the now-fixed
bugs becomes noise that obscures real ongoing errors. This patch
clears anything older than 24 hours so the next audit shows ONLY
post-fix errors (validates the fixes held).

Preserved:
  - Last 24h of errors — lets us compare the post-deploy log to the
    pre-deploy baseline. If something regresses, the new error fires
    fresh and we see it next to anything that survived.

Safe:
  - Error Log is a diagnostic log doctype, not transactional data.
    Has no FK constraints from other doctypes (Frappe queries it by
    name when surfacing the desk error link, but recently-resolved
    errors won't be referenced by users in flight).
  - Direct SQL DELETE (no per-doc validate cascade — Error Log has
    none anyway). Logs the deleted count.
  - Idempotent: running twice has no effect (nothing older than 24h
    on the second pass).
"""

import frappe


def execute():
    # Count first for the log line.
    pre = frappe.db.sql(
        """
        SELECT COUNT(*) FROM `tabError Log`
        WHERE creation < (NOW() - INTERVAL 1 DAY)
        """
    )[0][0]

    if not pre:
        print(
            "purge_error_log_preserve_24h: nothing to purge "
            "(no rows older than 24h)"
        )
        return

    frappe.db.sql(
        """
        DELETE FROM `tabError Log`
        WHERE creation < (NOW() - INTERVAL 1 DAY)
        """
    )
    frappe.db.commit()
    print(
        f"purge_error_log_preserve_24h: deleted {pre} Error Log row(s) "
        f"older than 24h. Recent rows preserved for post-deploy "
        f"regression watch."
    )
