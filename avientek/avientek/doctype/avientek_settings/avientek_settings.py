# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AvientekSettings(Document):
	def on_update(self):
		"""Rahul 2026-05-22: when the Issued Bank Edit Roles table
		changes, regenerate the Payment Request Form workflow so the
		new role pool flows through to `allow_edit` rows on every
		pre-Released state. Without this, admin edits to the table
		would only affect the JS field-unlock; the server-side
		workflow check would still gate on the previously-seeded
		roles until the next `bench migrate`.

		Tracks the previous value of the table via `doc.has_value_changed`
		to skip the re-seed when an unrelated field on the Settings was
		updated.
		"""
		try:
			if self.has_value_changed("issued_bank_edit_roles"):
				_reseed_payment_request_form_workflow()
		except Exception as e:
			frappe.log_error(
				f"Avientek Settings on_update PRF reseed: {e}",
				"AvientekSettings.on_update",
			)


def _reseed_payment_request_form_workflow():
	"""Re-run the PRF workflow seeder so the `allow_edit` rows match
	the current Avientek Settings → Issued Bank Edit Roles table."""
	from avientek.patches.create_payment_request_workflow import (
		execute as _seed,
	)
	if frappe.db.exists("Workflow", "Payment Request Form Approval"):
		frappe.delete_doc(
			"Workflow", "Payment Request Form Approval",
			ignore_permissions=True, force=True,
		)
		frappe.db.commit()
	_seed()
	frappe.db.commit()
	print(
		"[avientek_settings.on_update] Payment Request Form workflow "
		"rebuilt — issued_bank_edit_roles table change picked up."
	)
