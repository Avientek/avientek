"""Full GL rebuild for AVIENTEK TRADING LLC only.

Deletes ALL GL entries for the company and regenerates them by calling
make_gl_entries on every submitted voucher. Handles different method
signatures for different voucher types.

IMPORTANT: Only targets AVIENTEK TRADING LLC. No other company is affected.
"""

import frappe


def execute():
	company = "AVIENTEK TRADING LLC"

	if not frappe.db.exists("Company", company):
		print(f"[full_gl_rebuild] Company {company} not found, skipping")
		return

	print(f"[full_gl_rebuild] Starting full GL rebuild for {company}")

	# Step 1: Delete ALL GL entries for this company
	count = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabGL Entry` WHERE company = %s",
		company,
	)[0][0]
	print(f"[full_gl_rebuild] Deleting {count} GL entries...")

	frappe.db.sql("DELETE FROM `tabGL Entry` WHERE company = %s", company)
	frappe.db.commit()

	# Step 2: Skip any pending Repost Item Valuation entries
	frappe.db.sql(
		"""
		UPDATE `tabRepost Item Valuation`
		SET status = 'Skipped'
		WHERE company = %s AND status IN ('Queued', 'Failed', 'In Progress')
		""",
		company,
	)
	frappe.db.commit()

	# Step 3: Find ALL submitted vouchers
	# Group 1: Vouchers where make_gl_entries accepts (gl_entries=None, from_repost=True)
	repost_types = [
		"Sales Invoice",
		"Purchase Invoice",
		"Delivery Note",
		"Purchase Receipt",
		"Stock Entry",
		"Stock Reconciliation",
	]
	# Group 2: Vouchers where make_gl_entries takes no arguments
	simple_types = [
		"Payment Entry",
		"Journal Entry",
	]

	all_vouchers = []
	for vtype in repost_types:
		names = frappe.db.sql(
			"SELECT name FROM `tab{vt}` WHERE company = %s AND docstatus = 1 ORDER BY posting_date, creation".format(
				vt=vtype
			),
			company,
			pluck="name",
		)
		for name in names:
			all_vouchers.append({"type": vtype, "name": name, "group": "repost"})

	for vtype in simple_types:
		names = frappe.db.sql(
			"SELECT name FROM `tab{vt}` WHERE company = %s AND docstatus = 1 ORDER BY posting_date, creation".format(
				vt=vtype
			),
			company,
			pluck="name",
		)
		for name in names:
			all_vouchers.append({"type": vtype, "name": name, "group": "simple"})

	print(f"[full_gl_rebuild] Found {len(all_vouchers)} submitted vouchers to process")

	# Step 4: Regenerate GL entries
	success = 0
	errors = 0
	error_vouchers = []
	for i, v in enumerate(all_vouchers):
		try:
			doc = frappe.get_doc(v["type"], v["name"])
			if hasattr(doc, "make_gl_entries"):
				if v["group"] == "repost":
					doc.make_gl_entries(gl_entries=None, from_repost=True)
				else:
					doc.make_gl_entries()
				success += 1
		except Exception as e:
			errors += 1
			error_vouchers.append(f"{v['type']}/{v['name']}: {str(e)[:100]}")

		if (i + 1) % 100 == 0:
			frappe.db.commit()
			print(f"[full_gl_rebuild] Processed {i + 1}/{len(all_vouchers)} ({success} ok, {errors} errors)")

	frappe.db.commit()

	# Step 5: Clean up any partially created GL entries (imbalanced vouchers)
	imbalanced = frappe.db.sql(
		"""
		SELECT voucher_type, voucher_no
		FROM `tabGL Entry`
		WHERE company = %s AND is_cancelled = 0
		GROUP BY voucher_type, voucher_no
		HAVING ABS(SUM(debit) - SUM(credit)) > 1
		""",
		company,
		as_dict=True,
	)
	if imbalanced:
		for v in imbalanced:
			frappe.db.sql(
				"DELETE FROM `tabGL Entry` WHERE voucher_type = %s AND voucher_no = %s",
				(v.voucher_type, v.voucher_no),
			)
		frappe.db.commit()
		print(f"[full_gl_rebuild] Cleaned up {len(imbalanced)} imbalanced vouchers")

	# Final verification
	tb = frappe.db.sql(
		"SELECT SUM(debit) - SUM(credit) as diff FROM `tabGL Entry` WHERE company = %s AND is_cancelled = 0",
		company,
	)[0][0] or 0
	print(f"[full_gl_rebuild] DONE: {success} ok, {errors} errors. Trial Balance diff: {tb}")

	if error_vouchers:
		print(f"[full_gl_rebuild] Failed vouchers (first 10):")
		for ev in error_vouchers[:10]:
			print(f"  {ev}")
