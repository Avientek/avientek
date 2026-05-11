"""Copy the legacy single Avientek Settings role fields
(`quote_approval_role`, `quote_high_prob_creator_role`) into the new
multi-role child tables (`quote_approver_roles`, `quote_creator_roles`)
on first run.

Idempotent — only seeds the table if it's empty AND the legacy single
field is set AND the role still exists in DB. Subsequent migrates
won't disturb whatever admins added to the tables by hand.

Sammish 2026-05-13: this lets admins assign MULTIPLE approver / creator
roles via the Avientek Settings tables. The V3 workflow seeder
(seed_quotation_approval_v3_workflow.py) emits one transition row per
role on each side, so "any of these roles can approve" works out of
the box.
"""
import frappe


def execute():
	if not frappe.db.exists("DocType", "Avientek Settings"):
		print("[migrate_quote_role_singles_to_tables] Avientek Settings DocType missing — skipping")
		return
	if not frappe.db.exists("DocType", "Avientek Quote Role"):
		print("[migrate_quote_role_singles_to_tables] Avientek Quote Role child DocType missing — skipping (run migrate first to create it)")
		return

	sett = frappe.get_single("Avientek Settings")
	changed = False

	pairs = [
		("quote_approval_role", "quote_approver_roles", "Approval"),
		("quote_high_prob_creator_role", "quote_creator_roles", "Creator"),
	]
	for legacy_field, table_field, label in pairs:
		legacy_value = sett.get(legacy_field)
		existing_rows = sett.get(table_field) or []
		if existing_rows:
			print(f"[migrate_quote_role_singles_to_tables] {table_field}: already has {len(existing_rows)} row(s) — skipping {label} seed")
			continue
		if not legacy_value:
			print(f"[migrate_quote_role_singles_to_tables] {legacy_field}: empty — nothing to copy for {label}")
			continue
		if not frappe.db.exists("Role", legacy_value):
			print(f"[migrate_quote_role_singles_to_tables] {legacy_field}={legacy_value!r}: role missing in DB — skipping")
			continue
		sett.append(table_field, {"role": legacy_value})
		print(f"[migrate_quote_role_singles_to_tables] {table_field}: seeded with {legacy_value!r} from {legacy_field}")
		changed = True

	if changed:
		sett.flags.ignore_permissions = True
		sett.save()
		frappe.db.commit()
		print("[migrate_quote_role_singles_to_tables] Avientek Settings saved")
	else:
		print("[migrate_quote_role_singles_to_tables] no changes needed")
