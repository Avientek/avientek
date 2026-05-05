"""Inspect Custom DocPerm + Patch Log state for Sales Invoice + 'CSM' role."""
from __future__ import annotations

import frappe


def run():
    print("=" * 70)
    print(f"DOCPERM STATE DIAGNOSTIC  — site: {frappe.local.site}")
    print("=" * 70)

    # ── 1. Patch Log: have the perm patches run? ──
    print("\n[1] Patch Log entries for perm-related patches:")
    rows = frappe.db.sql(
        """SELECT patch, creation FROM `tabPatch Log`
           WHERE patch LIKE %s OR patch LIKE %s OR patch LIKE %s
           ORDER BY creation""",
        ("%ensure_sales_user_sales_invoice_perm%",
         "%grant_all_role_prf_draft_edit%",
         "%ensure_prf_draft_state_roles%"),
        as_dict=True,
    )
    if not rows:
        print("  (none of these patches have ever run)")
    for r in rows:
        print(f"  ✓ {r['patch']:55s} ran at {r['creation']}")

    # ── 2. Custom DocPerm rows on Sales Invoice ──
    print("\n[2] All Custom DocPerm on Sales Invoice (any role, any permlevel):")
    cdp = frappe.db.sql(
        """SELECT name, role, permlevel, `read`, `write`, `create`, submit,
                  export, creation, modified
           FROM `tabCustom DocPerm`
           WHERE parent = 'Sales Invoice'
           ORDER BY role, permlevel""", as_dict=True,
    )
    print(f"  {len(cdp)} rows:")
    for r in cdp:
        print(f"    {r['role']:35s} pl={r['permlevel']}  "
              f"r={r['read']} w={r['write']} c={r['create']} "
              f"s={r['submit']} ex={r['export']}  "
              f"created={r['creation']}  name={r['name']}")

    # ── 3. Check for CSM role + its perms ──
    print("\n[3] 'CSM' role lookup:")
    csm = frappe.db.sql(
        """SELECT name FROM `tabRole`
           WHERE name LIKE %s OR name LIKE %s""",
        ("%CSM%", "%Customer Success%"), as_dict=True,
    )
    print(f"  Roles matching CSM/Customer Success: {[r['name'] for r in csm]}")
    if csm:
        for r in csm:
            cdp_csm = frappe.db.sql(
                """SELECT parent, permlevel, `read`, `write`
                   FROM `tabCustom DocPerm`
                   WHERE role = %s ORDER BY parent""",
                (r["name"],), as_dict=True,
            )
            print(f"  Custom DocPerm rows for role '{r['name']}': {len(cdp_csm)}")
            for c in cdp_csm[:10]:
                print(f"    parent={c['parent']:35s} pl={c['permlevel']} "
                      f"r={c['read']} w={c['write']}")

    # ── 4. All Custom DocPerm rows for 'Sales Invoice- Custom' role ──
    print("\n[4] All Custom DocPerm for 'Sales Invoice- Custom' role:")
    sic = frappe.db.sql(
        """SELECT parent, permlevel, `read`, `write`, `create`, submit, export, creation
           FROM `tabCustom DocPerm`
           WHERE role = 'Sales Invoice- Custom'
           ORDER BY parent, permlevel""", as_dict=True,
    )
    print(f"  {len(sic)} rows:")
    for r in sic:
        print(f"    parent={r['parent']:35s} pl={r['permlevel']}  "
              f"r={r['read']} w={r['write']} c={r['create']} "
              f"s={r['submit']} ex={r['export']}")

    # ── 5. Check Standard DocPerm for Sales Invoice ──
    print("\n[5] Standard DocPerm (tabDocPerm) on Sales Invoice:")
    std = frappe.db.sql(
        """SELECT role, permlevel, `read`, `write`, `create`, submit, export
           FROM `tabDocPerm`
           WHERE parent = 'Sales Invoice'
           ORDER BY role, permlevel""", as_dict=True,
    )
    print(f"  {len(std)} rows:")
    for r in std:
        print(f"    {r['role']:35s} pl={r['permlevel']}  "
              f"r={r['read']} w={r['write']} c={r['create']} "
              f"s={r['submit']} ex={r['export']}")

    # ── 6. Verdict on Sales Invoice- Custom row ──
    print("\n[6] Quick verdict:")
    sic_si = [r for r in cdp if r["role"] == "Sales Invoice- Custom"]
    if sic_si:
        print(f"  ✓ Sales Invoice- Custom DocPerm on Sales Invoice EXISTS: {sic_si[0]['name']}")
    else:
        print(f"  ✗ Sales Invoice- Custom DocPerm on Sales Invoice MISSING")
    sales_user = [r for r in cdp if r["role"] == "Sales User"]
    if sales_user:
        print(f"  ✓ Sales User DocPerm on Sales Invoice EXISTS: {sales_user[0]['name']}")
    else:
        print(f"  ✗ Sales User DocPerm on Sales Invoice MISSING — `ensure_sales_user_sales_invoice_perm` patch may have run but row was later deleted")
