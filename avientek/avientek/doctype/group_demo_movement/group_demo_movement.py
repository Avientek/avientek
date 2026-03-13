import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today, getdate


class GroupDemoMovement(Document):

	def validate(self):
		self.validate_assets()
		self.total_assets = len(self.assets)

	def validate_assets(self):
		"""Check for duplicates and validate asset availability."""
		seen = set()
		for row in self.assets:
			if row.asset in seen:
				frappe.throw(
					_("Asset {0} is added more than once. Remove duplicates.").format(row.asset)
				)
			seen.add(row.asset)

			asset = frappe.db.get_value(
				"Asset", row.asset,
				["custom_is_demo_asset", "custom_dam_status", "asset_name", "company"],
				as_dict=True,
			)
			if not asset:
				frappe.throw(_("Asset {0} not found.").format(row.asset))

			if not asset.custom_is_demo_asset:
				frappe.throw(_("Asset {0} is not marked as a demo asset.").format(row.asset))

			# Fetch brand from Item
			if row.item_code and not row.brand:
				row.brand = frappe.db.get_value("Item", row.item_code, "brand") or ""

			# Set current status for display
			row.asset_status = asset.custom_dam_status or "Free"

			if self.movement_type == "Group Move Out":
				if asset.custom_dam_status and asset.custom_dam_status != "Free":
					frappe.throw(
						_("Asset {0} ({1}) is currently <b>{2}</b>. Only Free assets can be moved out.").format(
							row.asset, asset.asset_name, asset.custom_dam_status
						)
					)

			elif self.movement_type == "Group Return":
				if asset.custom_dam_status not in ("On Demo", "Issued as Standby"):
					frappe.throw(
						_("Asset {0} ({1}) is currently <b>{2}</b>. Only assets On Demo or Issued as Standby can be returned.").format(
							row.asset, asset.asset_name, asset.custom_dam_status or "Free"
						)
					)

	def on_submit(self):
		if self.movement_type == "Group Move Out":
			self._group_move_out()
		elif self.movement_type == "Group Return":
			self._group_return()

	def on_cancel(self):
		if self.movement_type == "Group Move Out":
			self._cancel_move_out()
		elif self.movement_type == "Group Return":
			self._cancel_return()
		frappe.db.set_value("Group Demo Movement", self.name, "status", "Cancelled")

	def _group_move_out(self):
		"""Create individual Demo Movement per asset and update statuses."""
		for row in self.assets:
			dm = frappe.new_doc("Demo Movement")
			dm.movement_type = "Move Out"
			dm.asset = row.asset
			dm.serial_number = row.serial_number
			dm.company = row.company or self.company
			dm.customer = self.customer
			dm.contact_person = self.contact_person
			dm.mobile = self.mobile
			dm.email = self.email
			dm.country = self.country
			dm.purpose = self.purpose
			dm.requested_salesperson = self.requested_salesperson
			dm.movement_date = self.movement_date
			dm.expected_return_date = self.expected_return_date
			dm.notes = _("Created from Group Demo Movement {0}").format(self.name)
			dm.flags.ignore_permissions = True
			dm.insert()
			dm.submit()

			# Store reference back to group
			frappe.db.set_value(
				"Group Demo Movement Asset",
				row.name,
				"demo_movement",
				dm.name,
			)

		frappe.db.set_value("Group Demo Movement", self.name, "status", "Open")

	def _group_return(self):
		"""Create individual Return Demo Movements and close matching Move Outs."""
		for row in self.assets:
			dm = frappe.new_doc("Demo Movement")
			dm.movement_type = "Return"
			dm.asset = row.asset
			dm.serial_number = row.serial_number
			dm.company = row.company or self.company
			dm.customer = self.customer
			dm.contact_person = self.contact_person
			dm.mobile = self.mobile
			dm.email = self.email
			dm.country = self.country
			dm.purpose = self.purpose
			dm.requested_salesperson = self.requested_salesperson
			dm.movement_date = self.movement_date
			dm.notes = _("Created from Group Demo Movement {0}").format(self.name)
			dm.flags.ignore_permissions = True
			dm.insert()
			dm.submit()

			frappe.db.set_value(
				"Group Demo Movement Asset",
				row.name,
				"demo_movement",
				dm.name,
			)

		frappe.db.set_value("Group Demo Movement", self.name, "status", "Completed")

	def _cancel_move_out(self):
		"""Cancel all individual Demo Movements created by this group."""
		for row in self.assets:
			if row.demo_movement:
				dm = frappe.get_doc("Demo Movement", row.demo_movement)
				if dm.docstatus == 1:
					dm.flags.ignore_permissions = True
					dm.cancel()

	def _cancel_return(self):
		"""Cancel all individual Return Demo Movements created by this group."""
		for row in self.assets:
			if row.demo_movement:
				dm = frappe.get_doc("Demo Movement", row.demo_movement)
				if dm.docstatus == 1:
					dm.flags.ignore_permissions = True
					dm.cancel()
