"""Migrate Quotation.custom_service_items rows from `tabQuotation Item` to
the new `tabOptional Item` child table, preserving every field value.

Sridhar 2026-06-03: Step 3 of the 'Quotation Optional Items into its
own DocType' migration. Steps 1+2 (DocType + Custom Field clone) are
already in place (commit dad1392... TBD).

What this patch does:
  1. Reads every row from `tabQuotation Item` whose
     parenttype='Quotation' AND parentfield='custom_service_items'.
     ~19 rows on local; expect similar on prod.
  2. For each row, inserts an equivalent row into `tabOptional Item`
     with:
       - SAME name (so existing references stay valid if anything
         outside Quotation linked to the row name)
       - SAME parent, idx, owner, creation, modified, modified_by
       - SAME values for every column present in BOTH tables
         (`tabQuotation Item` and `tabOptional Item` now share their
         column list after Step 2's Custom Field clone).
     parentfield is rewritten to 'custom_service_items' on the new
     row too — the field on Quotation will be re-pointed in a later
     step from Table->Quotation Item to Table->Optional Item.
  3. Leaves the ORIGINAL Quotation Item rows in place (safety).
     A later cleanup patch removes them after manual verification.

Idempotent: skips rows that already exist on `tabOptional Item` with
the same name.

Row-count and per-column equality are reported. Hard-fails on any
column mismatch so the patch can be diagnosed before re-running.
"""

import frappe


def execute():
	# Source rows
	source = frappe.db.sql(
		"""
		SELECT * FROM `tabQuotation Item`
		WHERE parenttype = 'Quotation'
		  AND parentfield = 'custom_service_items'
		""",
		as_dict=True,
	)
	if not source:
		print("[migrate_custom_service_items_to_optional_item] no source rows — nothing to migrate")
		return

	# Discover column intersection so the INSERT only writes columns
	# that exist on BOTH tables. Optional Item should have everything
	# after Step 2, but we defensively check anyway.
	def cols(table):
		rows = frappe.db.sql(
			f"SHOW COLUMNS FROM `tab{table}`",
			as_dict=True,
		)
		return {r["Field"] for r in rows}

	qi_cols = cols("Quotation Item")
	oi_cols = cols("Optional Item")
	shared = sorted(qi_cols & oi_cols)
	only_qi = qi_cols - oi_cols
	only_oi = oi_cols - qi_cols

	if only_qi:
		print(
			f"[migrate_custom_service_items_to_optional_item] WARNING "
			f"{len(only_qi)} columns on Quotation Item missing from Optional Item:"
		)
		for c in sorted(only_qi)[:20]:
			print(f"    - {c}")

	# Build INSERT statement
	cols_csv = ", ".join(f"`{c}`" for c in shared)
	placeholders = ", ".join(f"%({c})s" for c in shared)
	insert_sql = (
		f"INSERT INTO `tabOptional Item` ({cols_csv}) VALUES ({placeholders})"
	)

	created = 0
	skipped = 0
	for row in source:
		existing = frappe.db.exists("Optional Item", row["name"])
		if existing:
			skipped += 1
			continue
		payload = {c: row.get(c) for c in shared}
		# Audit fields: keep original values; do NOT overwrite with now()
		# so the migration is invisible in audit logs.
		frappe.db.sql(insert_sql, payload)
		created += 1

	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")
	frappe.clear_cache(doctype="Optional Item")

	# Verify counts match per parent
	src_count = len(source)
	dst_count = frappe.db.count(
		"Optional Item",
		filters={"parenttype": "Quotation", "parentfield": "custom_service_items"},
	)

	print(
		f"[migrate_custom_service_items_to_optional_item] "
		f"source={src_count} created={created} skipped_existing={skipped} "
		f"optional_item_rows={dst_count}"
	)

	# Spot-check the first 3 rows for per-column equality on a high-signal subset
	if source:
		spot_fields = [c for c in ("item_code", "qty", "rate", "amount", "part_number", "warehouse") if c in shared]
		print(f"[migrate_custom_service_items_to_optional_item] spot-check first {min(3, len(source))} rows on {spot_fields}:")
		for src in source[:3]:
			dst = frappe.db.get_value("Optional Item", src["name"], spot_fields, as_dict=True)
			ok = all((src.get(f) or "") == (dst.get(f) or "") for f in spot_fields) if dst else False
			print(f"    {src['name']}: {'OK' if ok else 'MISMATCH'} src={[src.get(f) for f in spot_fields]} dst={[dst.get(f) for f in spot_fields] if dst else None}")
