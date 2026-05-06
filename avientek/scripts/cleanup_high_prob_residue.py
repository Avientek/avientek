"""Remove leftover high-probability artefacts from any site that
tested feature/quotation-high-prob and has now switched back to master.

Idempotent. Re-running on a clean site is a no-op.

What it removes:
  - 6 DocFields on Avientek Settings (quote_high_prob_*)
  - DocType Quotation Action Request + its tab* table + tabPatch Log row
  - DocType Avientek Quotation Restricted Role + its tab* table
  - Workflow `Quotation Action Request Approval` + child rows
  - Workflow States: L1 Approved, L2 Approved, Executed
    (does NOT touch Pending / Rejected / Approved — those are common)
  - Workflow Action Masters: Approve L1, Approve L2

What it does NOT touch:
  - Any Role (no Role records were ever created by this feature)
  - Any User assignment (Has Role rows untouched)
  - Any Quotation
  - The avientek app code itself (the feature branch survives untouched)

Run:
    bench --site <site> execute avientek.scripts.cleanup_high_prob_residue.run
"""
import frappe


_HIGH_PROB_FIELDS = [
    "quote_high_prob_section",
    "quote_high_prob_l1_role",
    "quote_high_prob_l2_role",
    "quote_high_prob_column_break",
    "quote_high_prob_creator_role",
    "quote_high_prob_restricted_roles",
]
_DOCTYPES = [
    "Quotation Action Request",
    "Avientek Quotation Restricted Role",
]
_WORKFLOW = "Quotation Action Request Approval"
_OUR_WORKFLOW_STATES = ("L1 Approved", "L2 Approved", "Executed")
_OUR_WORKFLOW_ACTIONS = ("Approve L1", "Approve L2")


def run():
    print("=" * 70)
    print(f"HIGH-PROB CLEANUP — site: {frappe.local.site}")
    print("=" * 70)

    # 1. Delete the leftover DocFields on Avientek Settings.
    n_fields = frappe.db.sql(
        f"""DELETE FROM `tabDocField`
            WHERE parent = 'Avientek Settings'
              AND fieldname IN ({','.join(['%s']*len(_HIGH_PROB_FIELDS))})""",
        _HIGH_PROB_FIELDS,
    )
    # frappe.db.sql returns affected count via cursor.rowcount through a different path
    # Use explicit count to log
    remaining = frappe.db.sql(
        f"""SELECT fieldname FROM `tabDocField`
            WHERE parent = 'Avientek Settings'
              AND fieldname LIKE 'quote_high_prob%'""",
        as_dict=True,
    )
    print(f"  [1] Avientek Settings high-prob fields removed. "
          f"Remaining: {[r.fieldname for r in remaining] or 'none'}")

    # 2. Drop the workflow first (it references the doctypes).
    if frappe.db.exists("Workflow", _WORKFLOW):
        wf = frappe.get_doc("Workflow", _WORKFLOW)
        wf.is_active = 0
        wf.flags.ignore_permissions = True
        wf.save()  # de-activate so deletion doesn't fail
        try:
            frappe.delete_doc("Workflow", _WORKFLOW,
                              ignore_permissions=True, force=True)
            print(f"  [2] Workflow {_WORKFLOW!r}: DELETED")
        except Exception as e:
            # Last-ditch direct SQL.
            frappe.db.sql("DELETE FROM `tabWorkflow Document State` WHERE parent=%s",
                          (_WORKFLOW,))
            frappe.db.sql("DELETE FROM `tabWorkflow Transition` WHERE parent=%s",
                          (_WORKFLOW,))
            frappe.db.sql("DELETE FROM `tabWorkflow` WHERE name=%s",
                          (_WORKFLOW,))
            print(f"  [2] Workflow {_WORKFLOW!r}: forced-deleted via SQL ({e})")
    else:
        print(f"  [2] Workflow {_WORKFLOW!r}: already gone")

    # 3. Delete our workflow states (only the ones unique to us).
    for state in _OUR_WORKFLOW_STATES:
        if frappe.db.exists("Workflow State", state):
            try:
                frappe.delete_doc("Workflow State", state,
                                  ignore_permissions=True, force=True)
                print(f"  [3] Workflow State {state!r}: DELETED")
            except Exception as e:
                print(f"  [3] Workflow State {state!r}: skipped ({e})")
        else:
            print(f"  [3] Workflow State {state!r}: already gone")

    # 4. Delete our workflow action masters.
    for action in _OUR_WORKFLOW_ACTIONS:
        if frappe.db.exists("Workflow Action Master", action):
            try:
                frappe.delete_doc("Workflow Action Master", action,
                                  ignore_permissions=True, force=True)
                print(f"  [4] Workflow Action Master {action!r}: DELETED")
            except Exception as e:
                print(f"  [4] Workflow Action Master {action!r}: skipped ({e})")
        else:
            print(f"  [4] Workflow Action Master {action!r}: already gone")

    # 5. Drop the DocTypes (children first, parents second).
    for dt in _DOCTYPES:
        if frappe.db.exists("DocType", dt):
            try:
                frappe.delete_doc("DocType", dt,
                                  ignore_permissions=True, force=True)
                print(f"  [5] DocType {dt!r}: DELETED")
            except Exception as e:
                print(f"  [5] DocType {dt!r}: forced-delete via SQL ({e})")
                frappe.db.sql(
                    "DELETE FROM `tabDocField` WHERE parent=%s", (dt,))
                frappe.db.sql(
                    "DELETE FROM `tabDocType` WHERE name=%s", (dt,))
        # Drop the underlying MySQL table even if delete_doc didn't.
        if frappe.db.table_exists(dt):
            frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{dt}`")
            print(f"  [5] dropped table tab{dt}")

    # 6. Remove the seeder's Patch Log entry so a future re-deploy of the
    # feature branch can re-seed cleanly.
    for patch in (
        "avientek.patches.seed_quotation_action_request_workflow",
    ):
        if frappe.db.exists("Patch Log", {"patch": patch}):
            frappe.db.sql("DELETE FROM `tabPatch Log` WHERE patch=%s", (patch,))
            print(f"  [6] Patch Log row {patch!r}: removed (seeder will re-run on next migrate)")

    frappe.clear_cache()
    frappe.db.commit()
    print()
    print("✅  Cleanup complete.")
    print("    Avientek Settings should now load without the 'Not found' popup.")
    print("    Hard-refresh your browser (Cmd+Shift+R) to pick up the cleared cache.")
