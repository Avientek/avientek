"""Seed default Restricted Roles on Avientek Settings — Procurement L2,
Dispatch, Supply Chain, Logistics per BRD §2.1 (Quote Enhancement and
Notification, 2026-05-02).

Sridhar 2026-05-24 noted that Avientek Settings → Restricted Roles
table was empty on prod, so no role was treated as "Read-only on
Approved + 100%". BRD §2.1 lists Dispatch / Procurement / Supply Chain /
Logistics as the downstream teams that should see only Approved 100%
quotes.

Idempotent — adds each role only if not already in the table. Roles
that don't yet exist on the site are skipped with a WARN log (admin
can create the missing Role then re-run migrate to backfill).

Safe to re-run. Doesn't remove existing rows.
"""
import frappe

DEFAULT_RESTRICTED_ROLES = [
	"Procurement L2",
	"Dispatch",
	"Supply Chain",
	"Logistics",
]


def execute():
	if not frappe.db.exists("DocType", "Avientek Settings"):
		print("[seed_quotation_restricted_roles] Avientek Settings doctype missing — skipped")
		return

	settings = frappe.get_single("Avientek Settings")

	# Read existing rows so we only append new ones (idempotent).
	existing = {
		(r.role or "").strip()
		for r in (settings.get("quote_high_prob_restricted_roles") or [])
	}

	added = 0
	skipped_missing_role = []
	for role in DEFAULT_RESTRICTED_ROLES:
		if role in existing:
			continue
		if not frappe.db.exists("Role", role):
			skipped_missing_role.append(role)
			continue
		settings.append("quote_high_prob_restricted_roles", {"role": role})
		added += 1

	if added:
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		print(f"[seed_quotation_restricted_roles] Added {added} restricted role(s) to Avientek Settings")

	if skipped_missing_role:
		print(
			f"[seed_quotation_restricted_roles] WARN: these roles don't "
			f"exist on this site and were skipped: {skipped_missing_role}. "
			f"Create them via /app/role, then re-run `bench migrate` to "
			f"backfill."
		)

	if not added and not skipped_missing_role:
		print("[seed_quotation_restricted_roles] All default restricted roles already present — no change")
