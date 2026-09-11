"""Backfill Margin Value / Margin % / Markup Value / Markup % onto existing
Sales Order / Delivery Note / Sales Invoice items from their source Quotation
(#0520 / TSK-2026-00681, Orders.Mea — extended to DN 2026-09-11).

Creates the mirror fields first (after_migrate runs later than patches, so the
fields may not exist yet on the first migrate), then set-based backfills along
Quotation Item -> SO Item -> DN/SI Item. Display-only fields: no `modified` /
ledger change, safe on submitted / 2025 documents. Idempotent.
"""
import frappe


def execute():
	from avientek.migrate import (
		_create_margin_markup_carry_fields,
		_backfill_margin_markup_carry_fields,
	)
	_create_margin_markup_carry_fields()
	frappe.clear_cache(doctype="Sales Order Item")
	frappe.clear_cache(doctype="Delivery Note Item")
	frappe.clear_cache(doctype="Sales Invoice Item")
	_backfill_margin_markup_carry_fields()
