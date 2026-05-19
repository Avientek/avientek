"""Unblock Avientek modules on every Module Profile.

Jithin 2026-05-19: Rahul (GM-CS) couldn't see the Sales Team
workspace in his sidebar. Diagnostic traced it to a Module Profile
(`GM-CS-Module`) attached to those users that BLOCKS the Avientek
module entirely. Frappe v15's sidebar filter respects module-level
blocking — so even though the workspace is public and GM-CS users
have the required roles + read perms on Quotation, the workspace
disappears from their sidebar.

Other profiles on prod might do the same (e.g. profile names varying
between sites), so this patch scans ALL Module Profiles and removes
the Avientek + Avientek Reports entries from each profile's
`block_modules` table. After updating the profile, it re-saves each
affected user so their cached `User.block_modules` table syncs from
the profile.

Other blocked modules (Accounts, Payroll, etc.) are left alone —
those remain intentionally hidden.

Idempotent: only removes if currently blocked; re-runs are no-ops.
"""

import frappe


UNBLOCK = ("Avientek", "Avientek Reports")


def execute():
    profiles = frappe.db.get_all("Module Profile", pluck="name")
    total_users_resaved = 0
    total_profiles_changed = 0

    for profile in profiles:
        doc = frappe.get_doc("Module Profile", profile)
        keep = []
        removed = []
        for bm in (doc.block_modules or []):
            if bm.module in UNBLOCK:
                removed.append(bm.module)
            else:
                keep.append(bm)
        if not removed:
            continue

        doc.set("block_modules", keep)
        doc.flags.ignore_permissions = True
        doc.save()
        total_profiles_changed += 1

        # Re-apply the profile to users so their User.block_modules
        # table syncs to the new profile state.
        affected = frappe.db.get_all("User",
            filters={"module_profile": profile, "enabled": 1},
            pluck="name")
        for u in affected:
            if u in ("Administrator", "Guest"):
                continue
            try:
                user_doc = frappe.get_doc("User", u)
                user_doc.flags.ignore_permissions = True
                user_doc.save()
            except Exception as e:
                print(f"  warn: re-syncing {u}: {e}")
        total_users_resaved += len(affected)
        print(
            f"[unblock_avientek_module] {profile!r}: removed {removed}; "
            f"re-saved {len(affected)} user(s)"
        )

    if total_profiles_changed == 0:
        print("[unblock_avientek_module] no changes — every Module Profile already allows Avientek")
        return

    frappe.db.commit()

    # Clear cache so the sidebar picks up the new state immediately
    try:
        frappe.cache.delete_value("workspace_sidebar_items")
    except Exception:
        pass

    print(
        f"[unblock_avientek_module] total: {total_profiles_changed} profile(s) updated, "
        f"{total_users_resaved} user(s) re-saved"
    )
