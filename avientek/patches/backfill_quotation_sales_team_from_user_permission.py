"""Backfill missing `sales_team` rows on Quotations using owner's User Permission.

Sridhar 2026-06-01: Sales Team workspace Number Cards (Pending L2 Approvals
etc.) showed the same count to every user — User Permissions weren't
filtering because the quotes had ZERO `sales_team` rows. ERPNext's
`Quotation.get_permission_query_conditions` filters via
`sales_team[].sales_person` against the user's Sales Person UPs; with
no sales_team rows there's nothing to filter against, so every reader
sees the quote.

Strategy: for each Quotation that has no sales_team rows, look up the
OWNER's first (alphabetically earliest) Sales Person User Permission
and insert a single Sales Team row with that sales_person at 100%
allocation. UP then auto-applies on list views and Number Cards.

Owners without any Sales Person UP are LOGGED but skipped — the quotes
remain unscoped until a UP is created for that owner (a data fix, not
a code fix). Idempotent — only touches quotes with zero sales_team
rows, never overwrites existing assignments.
"""

import frappe
from frappe.utils import now_datetime


def execute():
	# 1. Discover unique owners of quotes missing sales_team
	owners = frappe.db.sql(
		"""
		SELECT q.owner, COUNT(*) AS quote_count
		FROM `tabQuotation` q
		WHERE NOT EXISTS (
			SELECT 1 FROM `tabSales Team` st WHERE st.parent = q.name
		)
		GROUP BY q.owner
		""",
		as_dict=True,
	)

	# 2. Resolve each owner → first Sales Person UP
	owner_to_sp = {}
	owners_without_up = []
	for row in owners:
		sp_row = frappe.db.sql(
			"""
			SELECT MIN(`for_value`) AS sp
			FROM `tabUser Permission`
			WHERE user = %s
			  AND allow = 'Sales Person'
			  AND (applicable_for IS NULL OR applicable_for = '')
			""",
			(row["owner"],),
			as_dict=True,
		)
		sp_value = (sp_row[0]["sp"] if sp_row else None) or None
		if sp_value:
			owner_to_sp[row["owner"]] = sp_value
		else:
			owners_without_up.append((row["owner"], row["quote_count"]))

	# 3. Insert one Sales Team row per backfillable quote
	backfilled = 0
	ts = now_datetime()
	for owner, sp_value in owner_to_sp.items():
		quote_names = frappe.db.sql_list(
			"""
			SELECT q.name
			FROM `tabQuotation` q
			WHERE q.owner = %s
			  AND NOT EXISTS (
				SELECT 1 FROM `tabSales Team` st WHERE st.parent = q.name
			  )
			""",
			(owner,),
		)
		for qn in quote_names:
			row_name = frappe.generate_hash("Sales Team", 10)
			frappe.db.sql(
				"""
				INSERT INTO `tabSales Team`
				(name, owner, creation, modified, modified_by, parent, parenttype,
				 parentfield, idx, docstatus, sales_person, allocated_percentage,
				 allocated_amount, incentives, commission_rate)
				VALUES
				(%(name)s, 'Administrator', %(ts)s, %(ts)s, 'Administrator',
				 %(parent)s, 'Quotation', 'sales_team', 1, 0,
				 %(sp)s, 100, 0, 0, 0)
				""",
				{"name": row_name, "ts": ts, "parent": qn, "sp": sp_value},
			)
			backfilled += 1

	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")

	print("[backfill_quotation_sales_team_from_user_permission]")
	print(f"  Owners mapped via Sales Person UP: {len(owner_to_sp)}")
	print(f"  Quotes backfilled with sales_team row: {backfilled}")
	print(f"  Owners WITHOUT Sales Person UP (skipped):")
	for owner, count in sorted(owners_without_up, key=lambda x: -x[1]):
		print(f"    {owner}: {count} quotes")
