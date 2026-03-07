# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_link_to_form, now_datetime

import erpnext
from erpnext.accounts.general_ledger import (
	make_gl_entries as _make_gl_entries,
	make_reverse_gl_entries,
)
from erpnext.accounts.utils import get_fiscal_year
from erpnext.assets.doctype.asset.depreciation import (
	depreciate_asset,
	get_depreciation_accounts,
	get_disposal_account_and_cost_center,
	reset_depreciation_schedule,
	reverse_depreciation_entry_made_after_disposal,
)
from erpnext.assets.doctype.asset_activity.asset_activity import add_asset_activity
from erpnext.stock import get_warehouse_account_map
from erpnext.stock.stock_ledger import make_sl_entries


class AssetDecapitalization(Document):

	def validate(self):
		self.validate_asset()
		self.validate_target_item()
		self.set_asset_values()
		self.set_posting_time()
		self.calculate_gain_loss()
		self._populate_items_table()

	def validate_asset(self):
		asset_doc = frappe.db.get_value(
			"Asset", self.asset,
			["docstatus", "status"],
			as_dict=True,
		)
		if not asset_doc:
			frappe.throw(_("Asset {0} does not exist").format(self.asset))
		if asset_doc.docstatus != 1:
			frappe.throw(_("Asset {0} must be submitted").format(self.asset))
		if asset_doc.status in ("Cancelled", "Sold", "Scrapped", "Capitalized"):
			frappe.throw(
				_("Asset {0} cannot be decapitalized — it is already {1}").format(
					self.asset, asset_doc.status
				)
			)

	def validate_target_item(self):
		is_stock = frappe.get_cached_value("Item", self.target_item_code, "is_stock_item")
		if not is_stock:
			frappe.throw(
				_("Target Item {0} must be a stock item (Is Stock Item must be enabled)").format(
					self.target_item_code
				)
			)

	def set_asset_values(self):
		asset = frappe.get_doc("Asset", self.asset)
		self.gross_purchase_amount = flt(asset.gross_purchase_amount)
		self.value_after_depreciation = flt(asset.get_value_after_depreciation())
		self.accumulated_depreciation = flt(self.gross_purchase_amount) - flt(self.value_after_depreciation)
		if not self.entry_value:
			self.entry_value = self.value_after_depreciation

	def set_posting_time(self):
		if not self.posting_time:
			self.posting_time = now_datetime().strftime("%H:%M:%S")

	def calculate_gain_loss(self):
		self.gain_loss_amount = flt(self.value_after_depreciation) - flt(self.entry_value)

	def _populate_items_table(self):
		"""Populate hidden items child table for ERPNext stock reposting compatibility."""
		qty = flt(self.target_qty) or 1
		rate = flt(self.entry_value) / qty
		stock_uom = frappe.get_cached_value("Item", self.target_item_code, "stock_uom")
		item_name = frappe.get_cached_value("Item", self.target_item_code, "item_name")

		self.items = []
		self.append("items", {
			"item_code": self.target_item_code,
			"item_name": item_name,
			"warehouse": self.target_warehouse,
			"qty": qty,
			"valuation_rate": rate,
			"amount": flt(self.entry_value),
			"stock_uom": stock_uom,
			"incoming_rate": rate,
		})

	# ── Submit ──────────────────────────────────────────────────

	def on_submit(self):
		self._depreciate_asset_if_needed()
		self._create_stock_ledger_entry()
		self._create_gl_entries()
		self._update_asset()

	def _depreciate_asset_if_needed(self):
		"""Bring depreciation current up to posting_date (mirrors scrap_asset pattern)."""
		asset = frappe.get_doc("Asset", self.asset)
		if asset.calculate_depreciation and asset.status != "Fully Depreciated":
			notes = _(
				"This schedule was created when Asset {0} was decapitalized via {1}."
			).format(
				get_link_to_form("Asset", self.asset),
				get_link_to_form("Asset Decapitalization", self.name),
			)
			depreciate_asset(asset, self.posting_date, notes)
			asset.reload()
			self.value_after_depreciation = flt(asset.get_value_after_depreciation())
			self.accumulated_depreciation = flt(self.gross_purchase_amount) - flt(self.value_after_depreciation)
			self.calculate_gain_loss()
			self.db_set({
				"value_after_depreciation": self.value_after_depreciation,
				"accumulated_depreciation": self.accumulated_depreciation,
				"gain_loss_amount": self.gain_loss_amount,
			})

	def _create_stock_ledger_entry(self):
		"""Create SLE for stock receipt into target warehouse."""
		item_row = self.items[0]
		qty = flt(item_row.qty) or 1
		rate = flt(self.entry_value) / qty

		sle = frappe._dict({
			"item_code": item_row.item_code,
			"warehouse": item_row.warehouse,
			"actual_qty": flt(qty),
			"incoming_rate": rate,
			"posting_date": self.posting_date,
			"posting_time": self.posting_time or "00:00:00",
			"fiscal_year": get_fiscal_year(self.posting_date, company=self.company)[0],
			"voucher_type": self.doctype,
			"voucher_no": self.name,
			"voucher_detail_no": item_row.name,
			"stock_uom": item_row.stock_uom,
			"company": self.company,
			"is_cancelled": 0,
		})

		if self.serial_no:
			sle["serial_no"] = self.serial_no
		if self.batch_no:
			sle["batch_no"] = self.batch_no

		make_sl_entries([sle])

	def _build_gl_entry(self, args):
		"""Build a GL Entry dict with common fields."""
		fiscal_year = get_fiscal_year(self.posting_date, company=self.company)[0]
		gl = frappe._dict({
			"company": self.company,
			"posting_date": self.posting_date,
			"fiscal_year": fiscal_year,
			"voucher_type": self.doctype,
			"voucher_no": self.name,
			"debit": 0,
			"credit": 0,
			"debit_in_account_currency": 0,
			"credit_in_account_currency": 0,
			"is_opening": "No",
			"remarks": _("Asset Decapitalization"),
		})
		gl.update(args)

		# Mirror debit/credit into account_currency fields if not set
		if gl.debit and not gl.debit_in_account_currency:
			gl.debit_in_account_currency = gl.debit
		if gl.credit and not gl.credit_in_account_currency:
			gl.credit_in_account_currency = gl.credit

		return gl

	def _create_gl_entries(self):
		"""Create GL entries directly (no Journal Entry)."""
		gl_entries = []

		asset = frappe.get_doc("Asset", self.asset)
		fixed_asset_account, accumulated_depr_account, _dep_exp = get_depreciation_accounts(
			asset.asset_category, asset.company
		)
		_disposal_account, depreciation_cost_center = get_disposal_account_and_cost_center(
			asset.company
		)
		disposal_account = self.gain_loss_account or _disposal_account
		cost_center = self.cost_center or depreciation_cost_center

		# 1. Debit Warehouse Account (stock received)
		if erpnext.is_perpetual_inventory_enabled(self.company):
			warehouse_account_map = get_warehouse_account_map(self.company)
			wh_account = warehouse_account_map[self.target_warehouse]["account"]

			# Read the SLE stock_value_difference for accuracy
			stock_value_diff = frappe.db.get_value(
				"Stock Ledger Entry",
				{"voucher_type": self.doctype, "voucher_no": self.name},
				"stock_value_difference",
			) or flt(self.entry_value)

			gl_entries.append(self._build_gl_entry({
				"account": wh_account,
				"against": fixed_asset_account,
				"debit": flt(stock_value_diff),
				"cost_center": cost_center,
				"remarks": _("Accounting Entry for Stock"),
			}))

		# 2. Credit Fixed Asset Account (gross purchase amount)
		gl_entries.append(self._build_gl_entry({
			"account": fixed_asset_account,
			"against": self.target_warehouse,
			"credit": flt(self.gross_purchase_amount),
			"cost_center": cost_center,
		}))

		# 3. Debit Accumulated Depreciation
		if flt(self.accumulated_depreciation):
			gl_entries.append(self._build_gl_entry({
				"account": accumulated_depr_account,
				"against": fixed_asset_account,
				"debit": flt(self.accumulated_depreciation),
				"cost_center": cost_center,
			}))

		# 4. Gain / Loss on disposal
		gain_loss = flt(self.gain_loss_amount)
		if gain_loss:
			if gain_loss > 0:
				# Loss: book value > entry value
				gl_entries.append(self._build_gl_entry({
					"account": disposal_account,
					"against": fixed_asset_account,
					"debit": abs(gain_loss),
					"cost_center": cost_center,
					"remarks": _("Loss on Asset Decapitalization"),
				}))
			else:
				# Gain: entry value > book value
				gl_entries.append(self._build_gl_entry({
					"account": disposal_account,
					"against": fixed_asset_account,
					"credit": abs(gain_loss),
					"cost_center": cost_center,
					"remarks": _("Gain on Asset Decapitalization"),
				}))

		if gl_entries:
			_make_gl_entries(gl_entries)

	def _update_asset(self):
		frappe.db.set_value("Asset", self.asset, {
			"disposal_date": self.posting_date,
			"journal_entry_for_scrap": self.name,
			"custom_is_demo_asset": 0,
		})

		asset = frappe.get_doc("Asset", self.asset)
		asset.set_status("Scrapped")

		add_asset_activity(
			self.asset,
			_("Asset decapitalized to stock via {0}").format(
				get_link_to_form("Asset Decapitalization", self.name)
			),
		)

	# ── Cancel ──────────────────────────────────────────────────

	def on_cancel(self):
		self._cancel_serial_and_batch_bundles()
		self._reverse_stock_ledger_entry()
		self._reverse_gl_entries()
		self._restore_asset()
		# GL entries, SLE entries and SABBs all reference us via voucher_type/
		# voucher_no dynamic links. They are properly reversed above, so skip
		# Frappe's post-cancel link check.
		self.flags.ignore_links = True

	def _cancel_serial_and_batch_bundles(self):
		"""Cancel all Serial and Batch Bundles linked to this document.

		Must run inside on_cancel (before check_no_back_links_exist) so
		Frappe sees the SABBs as docstatus=2 and skips them in the link check.
		"""
		# Find SABBs via the dynamic-link (voucher_type / voucher_no)
		sabbs = frappe.get_all(
			"Serial and Batch Bundle",
			filters={"voucher_type": self.doctype, "voucher_no": self.name},
			pluck="name",
		)
		for sabb_name in sabbs:
			frappe.db.set_value(
				"Serial and Batch Bundle", sabb_name,
				{"is_cancelled": 1, "docstatus": 2, "voucher_no": ""},
			)

		# Delink from child rows
		for row in self.get("items"):
			if row.get("serial_and_batch_bundle"):
				row.db_set("serial_and_batch_bundle", None)
			if row.get("rejected_serial_and_batch_bundle"):
				row.db_set("rejected_serial_and_batch_bundle", None)
			if row.get("current_serial_and_batch_bundle"):
				row.db_set("current_serial_and_batch_bundle", None)

	def _reverse_stock_ledger_entry(self):
		"""Create reverse SLE to undo stock receipt."""
		item_row = self.items[0]
		qty = flt(item_row.qty) or 1
		rate = flt(self.entry_value) / qty

		sle = frappe._dict({
			"item_code": item_row.item_code,
			"warehouse": item_row.warehouse,
			"actual_qty": flt(qty),
			"incoming_rate": rate,
			"posting_date": self.posting_date,
			"posting_time": self.posting_time or "00:00:00",
			"fiscal_year": get_fiscal_year(self.posting_date, company=self.company)[0],
			"voucher_type": self.doctype,
			"voucher_no": self.name,
			"voucher_detail_no": item_row.name,
			"stock_uom": item_row.stock_uom,
			"company": self.company,
			"is_cancelled": 1,
		})

		make_sl_entries([sle])

	def _reverse_gl_entries(self):
		"""Reverse all GL entries for this voucher."""
		make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

	def _restore_asset(self):
		asset = frappe.get_doc("Asset", self.asset)

		# Clear disposal fields FIRST — reset_depreciation_schedule calls
		# asset.save() which validates journal_entry_for_scrap as a Link to
		# "Journal Entry". We stored an Asset Decapitalization name, so the
		# validation would fail if we don't clear it beforehand.
		asset.db_set("disposal_date", None)
		asset.db_set("journal_entry_for_scrap", None)
		asset.db_set("custom_is_demo_asset", 1)

		if asset.calculate_depreciation:
			asset.reload()
			reverse_depreciation_entry_made_after_disposal(asset, self.posting_date)
			notes = _(
				"This schedule was created when Asset {0} was restored after "
				"Asset Decapitalization {1} was cancelled."
			).format(
				get_link_to_form("Asset", self.asset),
				get_link_to_form("Asset Decapitalization", self.name),
			)
			reset_depreciation_schedule(asset, self.posting_date, notes)

		asset.set_status()

		add_asset_activity(
			self.asset,
			_("Asset restored after Asset Decapitalization {0} was cancelled").format(
				get_link_to_form("Asset Decapitalization", self.name)
			),
		)
