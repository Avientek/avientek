import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today, flt, now, getdate


class RMACase(Document):

	def validate(self):
		if self.standby_unit and self.demo_asset and self.standby_unit == self.demo_asset:
			frappe.throw("Standby Unit cannot be the same as the Faulty Unit.")

	def before_save(self):
		self.sync_asset_values()
		self.auto_close_date()

	def on_submit(self):
		"""On submit, issue standby unit if assigned."""
		if self.standby_unit:
			frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Issued as Standby")

	def on_cancel(self):
		"""On cancel, free the standby unit."""
		if self.standby_unit:
			frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Free")

	def on_update_after_submit(self):
		"""Allow status changes and standby unit updates after submit."""
		self.auto_close_date()
		self._sync_standby_status()

	def sync_asset_values(self):
		"""Pull financial values from linked Asset."""
		if not self.demo_asset:
			return
		a = frappe.db.get_value("Asset", self.demo_asset, [
			"gross_purchase_amount", "value_after_depreciation", "company",
		], as_dict=True)
		if a:
			self.gross_asset_value = flt(a.gross_purchase_amount)
			self.net_asset_value = flt(a.value_after_depreciation)
			self.accumulated_depreciation = flt(a.gross_purchase_amount) - flt(a.value_after_depreciation)
			if a.company:
				currency = frappe.db.get_value("Company", a.company, "default_currency")
				self.asset_currency = currency or "AED"

	def auto_close_date(self):
		"""Set closed_date when status moves to Closed/Cancelled."""
		if self.status in ("Closed", "Cancelled") and not self.closed_date:
			self.closed_date = today()
		elif self.status not in ("Closed", "Cancelled"):
			self.closed_date = None

	def _sync_standby_status(self):
		"""Update standby unit Asset status based on RMA case changes."""
		old_doc = self.get_doc_before_save()
		old_standby = old_doc.standby_unit if old_doc else None

		# Standby was returned (cleared)
		if old_standby and not self.standby_unit:
			frappe.db.set_value("Asset", old_standby, "custom_dam_status", "Free")
			return

		# Standby was swapped to a different asset
		if old_standby and self.standby_unit and old_standby != self.standby_unit:
			frappe.db.set_value("Asset", old_standby, "custom_dam_status", "Free")
			frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Issued as Standby")
			return

		# Standby exists — sync based on RMA status
		if self.standby_unit:
			if self.status in ("Closed", "Cancelled", "Replaced"):
				frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Free")
			else:
				current = frappe.db.get_value("Asset", self.standby_unit, "custom_dam_status")
				if current in ("Free", None, ""):
					frappe.db.set_value("Asset", self.standby_unit, "custom_dam_status", "Issued as Standby")

	def add_log(self, log_type, description):
		"""Append an entry to the Case Log child table."""
		self.append("case_log", {
			"log_date": now(),
			"log_type": log_type,
			"logged_by": frappe.session.user,
			"description": description,
		})


@frappe.whitelist()
def check_warranty(customer=None, serial_no=None, item_code=None):
	"""Look up active Warranty List records for a customer + serial/item."""
	filters = {"docstatus": 1, "status": ["in", ["Under Warranty", "Expired"]]}

	if customer:
		filters["customer"] = customer

	if serial_no:
		filters["serial_no"] = ["like", f"%{serial_no}%"]
	elif item_code:
		filters["item_code"] = item_code

	warranties = frappe.get_all(
		"Warranty List",
		filters=filters,
		fields=[
			"name", "status", "item_code", "item_name", "serial_no",
			"batch_no", "warranty_start_date", "warranty_end_date",
			"days_remaining", "customer", "delivery_note",
		],
		order_by="warranty_end_date desc",
		limit=20,
	)

	return warranties


@frappe.whitelist()
def check_availability(item_code=None, company=None):
	"""Check available demo assets and stock for a given item."""
	result = {"demo_assets": [], "stock": []}

	if not item_code:
		return result

	# Free demo assets for this item
	asset_filters = {
		"custom_is_demo_asset": 1,
		"docstatus": 0,
		"custom_dam_status": "Free",
		"item_code": item_code,
	}
	if company:
		asset_filters["company"] = company

	result["demo_assets"] = frappe.get_all(
		"Asset",
		filters=asset_filters,
		fields=["name", "asset_name", "item_code", "location", "company"],
		limit=20,
	)

	# Stock availability (warehouse-wise) — filter by company via Warehouse
	if company:
		warehouses = frappe.get_all("Warehouse", filters={"company": company}, pluck="name")
		stock_filters = {"item_code": item_code, "actual_qty": [">", 0], "warehouse": ["in", warehouses]}
	else:
		stock_filters = {"item_code": item_code, "actual_qty": [">", 0]}

	result["stock"] = frappe.get_all(
		"Bin",
		filters=stock_filters,
		fields=["warehouse", "actual_qty", "reserved_qty"],
		order_by="actual_qty desc",
		limit=20,
	)

	return result


@frappe.whitelist()
def create_standby_capitalization(rma_case, item_code, company, warehouse, asset_location):
	"""Create a draft Asset Capitalization from stock for standby unit issuance."""
	if not frappe.has_permission("Asset Capitalization", "create"):
		frappe.throw(_("You don't have permission to create Asset Capitalization"))

	item = frappe.get_cached_doc("Item", item_code)

	ac = frappe.new_doc("Asset Capitalization")
	ac.capitalization_method = "Create a new composite asset"
	ac.company = company
	ac.posting_date = today()
	ac.target_item_code = item_code
	ac.target_item_name = item.item_name
	ac.target_qty = 1
	ac.target_asset_location = asset_location
	ac.target_is_fixed_asset = 1

	# Add stock item as source
	ac.append("stock_items", {
		"item_code": item_code,
		"warehouse": warehouse,
		"stock_qty": 1,
		"stock_uom": item.stock_uom,
	})

	ac.insert(ignore_permissions=True)

	# Update RMA Case with standby source info
	frappe.db.set_value("RMA Case", rma_case, "standby_source", "Capitalized from Stock")

	frappe.msgprint(
		_("Asset Capitalization {0} created as draft. Submit it to generate the standby asset.").format(
			f'<a href="/app/asset-capitalization/{ac.name}">{ac.name}</a>'
		),
		title=_("Capitalization Created"),
		indicator="blue",
	)

	return ac.name
