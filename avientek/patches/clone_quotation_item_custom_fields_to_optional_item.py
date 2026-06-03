"""Replicate every Quotation Item Custom Field onto Optional Item.

Sridhar 2026-06-03: stepping the new 'Optional Item' child doctype to
field-parity with 'Quotation Item' so the data migration for the 19
existing `custom_service_items` rows is a straight column-by-column
copy (no field-not-found errors, no silent data loss).

Quotation Item has 85 Custom Fields on prod / local — covers
part_number, brand extras, custom_markup_*, custom_finance_*,
custom_transport_*, custom_incentive_*, costing-sheet helpers, etc.

This patch:
  - For each Custom Field on Quotation Item, create an equivalent
    Custom Field on Optional Item with identical fieldname + all
    relevant attributes (fieldtype, label, options, default, depends_on,
    read_only, hidden, in_list_view, in_standard_filter, allow_on_submit,
    no_copy, translatable, description, length, precision, fetch_from,
    link_filters, mandatory_depends_on, read_only_depends_on, columns,
    permlevel, bold).
  - Skip if the equivalent already exists on Optional Item (idempotent).
  - Preserve `insert_after` references by name; if the target field
    isn't on Optional Item yet, the new row goes to the end of the
    field_order — Frappe will rebuild positions on the next bench
    migrate run anyway.

Idempotent. Safe to re-run.

Step 2 of the 'Quotation Optional Items into own DocType' migration.
Step 1 (DocType creation) was done manually. Steps 3+ (data copy,
code references, field switch, cleanup) follow in their own patches.
"""

import frappe


# Attributes worth copying from a Custom Field row to keep the new
# row functionally identical. Includes display-control flags, value
# constraints, search behaviour, fetch logic. Skips audit columns
# (creation, owner, modified_by) — they get fresh values on insert.
COPY_ATTRS = (
	"fieldtype",
	"label",
	"options",
	"default",
	"description",
	"depends_on",
	"mandatory_depends_on",
	"read_only_depends_on",
	"hidden",
	"read_only",
	"reqd",
	"unique",
	"allow_on_submit",
	"no_copy",
	"in_list_view",
	"in_standard_filter",
	"in_global_search",
	"in_preview",
	"bold",
	"translatable",
	"length",
	"precision",
	"width",
	"columns",
	"permlevel",
	"fetch_from",
	"fetch_if_empty",
	"link_filters",
	"insert_after",
	"collapsible",
	"collapsible_depends_on",
	"ignore_user_permissions",
	"ignore_xss_filter",
	"allow_in_quick_entry",
	"print_hide",
	"print_hide_if_no_value",
	"report_hide",
	"non_negative",
	"is_virtual",
	"hide_border",
	"hide_days",
	"hide_seconds",
	"print_width",
	"search_index",
	"sort_options",
	"placeholder",
	"show_dashboard",
)


def execute():
	src = frappe.get_all(
		"Custom Field",
		filters={"dt": "Quotation Item"},
		fields=["name", "fieldname"] + list(COPY_ATTRS),
		order_by="idx asc",
	)
	if not src:
		print("[clone_quotation_item_custom_fields_to_optional_item] no source Custom Fields on Quotation Item — nothing to clone")
		return

	created = 0
	skipped = 0
	for row in src:
		new_name = f"Optional Item-{row['fieldname']}"
		if frappe.db.exists("Custom Field", new_name):
			skipped += 1
			continue
		cf = frappe.new_doc("Custom Field")
		cf.dt = "Optional Item"
		cf.fieldname = row["fieldname"]
		for attr in COPY_ATTRS:
			val = row.get(attr)
			if val in (None, ""):
				continue
			cf.set(attr, val)
		# Some attrs only make sense on certain fieldtypes; let Frappe
		# normalise via the regular insert path.
		cf.insert(ignore_permissions=True)
		created += 1

	frappe.db.commit()
	frappe.clear_cache(doctype="Optional Item")
	frappe.clear_cache(doctype="Quotation Item")
	print(
		f"[clone_quotation_item_custom_fields_to_optional_item] "
		f"source={len(src)} created={created} skipped_existing={skipped}"
	)
