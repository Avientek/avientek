"""One-time Error Log full wipe — delete ALL rows.

Companion to the 2026-06-17 production-ready sweep. After the fixes
above ship (Reward Payable account_type drift, _assign_todo
ignore_permissions, backfilled failed JVs, plus the already-merged
block_print and Quote tax fixes), the legacy backlog of Error Log
rows attributable to the now-fixed bugs becomes pure noise. This
patch clears EVERY row so the post-deploy log starts empty —
any new error after the deploy reflects either:

  a) a fix didn't hold (regression), OR
  b) a genuinely new bug the audit didn't surface.

Either way, signal is now obvious — no baseline noise to filter past.

Run order matters (registered after the JV fixes in patches.txt):
  1. fix_reward_payable_account_type_drift
  2. backfill_failed_reward_incentive_jvs
  3. purge_error_log_full_wipe  ← this patch

Frappe tracks executed patches in tabPatch Log so this runs ONCE.
Idempotent on re-run (count is 0 after first execution).

Safe:
  - Error Log is a diagnostic log doctype, no transactional data.
  - No FK constraints from other doctypes reference it.
  - Direct SQL DELETE (Error Log has no validate cascade).
"""

import frappe


def execute():
    pre = frappe.db.sql("SELECT COUNT(*) FROM `tabError Log`")[0][0]

    if not pre:
        print("purge_error_log_full_wipe: already empty — nothing to purge")
        return

    frappe.db.sql("DELETE FROM `tabError Log`")
    frappe.db.commit()
    print(
        f"purge_error_log_full_wipe: deleted {pre} Error Log row(s). "
        f"Post-deploy errors will now show without baseline noise."
    )
