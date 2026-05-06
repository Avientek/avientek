"""Verify the roles Sridhar mapped (2026-05-06) actually exist in the
DB on this site. If any are missing, the workflow seeder will refuse
to create transitions for them.

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.check_quote_high_prob_roles.run
"""
import frappe


REQUIRED = [
    # (role_name, purpose)
    ("Sales support L2",  "Quotation team / Quote creators / can create QAR"),
    ("GM-CS",             "Quote L1 approver"),
    ("CS",                "Quote L2 approver"),
    ("Procurement L2",    "Restricted (Dispatch team) — sees only Approved+100"),
    ("System Manager",    "Bypass"),
]


def run():
    print("=" * 70)
    print(f"QUOTATION HIGH-PROB — role existence check on {frappe.local.site}")
    print("=" * 70)
    missing = []
    for role, purpose in REQUIRED:
        exists = bool(frappe.db.exists("Role", role))
        # Count enabled users assigned to this role.
        n_users = 0
        if exists:
            n_users = frappe.db.sql(
                """SELECT COUNT(DISTINCT hr.parent) FROM `tabHas Role` hr
                   INNER JOIN `tabUser` u ON u.name = hr.parent
                   WHERE hr.role = %s AND u.enabled = 1""",
                (role,),
            )[0][0]
        flag = "OK" if exists else "MISSING"
        print(f"  {flag:7s}  {role:22s}  ({purpose})  users_assigned={n_users}")
        if not exists:
            missing.append(role)

    print()
    if missing:
        print(f"❌  {len(missing)} role(s) MISSING — they need to be created on")
        print(f"    this site (and on production) before the workflow + RBAC")
        print(f"    will work end-to-end:")
        for r in missing:
            print(f"      - {r}")
        print()
        print("    To create on Frappe Cloud System Console:")
        for r in missing:
            print(f"      frappe.get_doc({{'doctype':'Role','role_name':"
                  f"{r!r},'desk_access':1}}).insert(ignore_permissions=True)")
    else:
        print(f"✅  all {len(REQUIRED)} roles present.")
    return {"missing": missing,
            "roles": [r for r, _ in REQUIRED]}
