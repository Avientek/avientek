"""Unlock `probability` and `probabilities` Custom Fields after submit.

Sridhar 2026-05-27 (Probability BRD, Jithin/FM approved): Sales needs
to update probability on submitted Quotations directly. The earlier
patch `lock_quotation_probability_after_submit` (Jithin's earlier ask)
flipped `allow_on_submit=0`. New BRD reverses that — but adds an
approval gate: downgrades from ≥75% to <75% require a "Reason for
Change" + management approval. The gate is enforced in
`avientek.events.quotation.validate_probability_change_approval` and
the JS popup in public/js/quotation.js.

Idempotent — re-running is a no-op once the fields are unlocked.
"""

import frappe


def execute():
	fields = [
		"Quotation-probability",
		"Quotation-probabilities",
	]
	for name in fields:
		if not frappe.db.exists("Custom Field", name):
			print(f"[unlock_quotation_probability_after_submit] {name} missing, skipping")
			continue
		current = frappe.db.get_value("Custom Field", name, "allow_on_submit")
		if current == 1:
			print(f"[unlock_quotation_probability_after_submit] {name} already unlocked")
			continue
		frappe.db.set_value(
			"Custom Field", name, "allow_on_submit", 1,
			update_modified=False,
		)
		print(f"[unlock_quotation_probability_after_submit] {name} -> allow_on_submit=1")

	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
