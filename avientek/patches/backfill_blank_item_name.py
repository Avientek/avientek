"""Backfill Item.item_name for items imported with a blank name.

Some items (e.g. I030402-I030405) were imported with a NULL/empty item_name.
item_name is mandatory on transaction item rows, so these items break any
document they're added to — surfaced by the ZATCA compliance check
("Sales Invoice Item Row #1: Value missing for: Item Name", 2026-07-05).

The runtime safety net (avientek.events.utils.fill_missing_item_defaults) now
falls back to item_code, but the Item master itself should be correct too.
This sets item_name = item_code for every item whose name is blank.

Idempotent: only touches blank names; safe to re-run on every migrate.
"""
import frappe


def execute():
    names = frappe.db.sql_list(
        "SELECT name FROM `tabItem` WHERE item_name IS NULL OR item_name = ''"
    )
    for name in names:
        frappe.db.set_value("Item", name, "item_name", name, update_modified=False)
    if names:
        frappe.db.commit()
    print(f"[backfill_blank_item_name] set item_name = item_code for {len(names)} item(s)")
