"""One-time patch v2 to fix ALL stock account GL imbalances for AVIENTEK TRADING LLC.

Cleans up Stock-in-Trade AND Demo Stock GL entries for KSA company and
regenerates clean GL entries from SLE by calling make_gl_entries on each voucher.
"""

import frappe


def execute():
	company = "AVIENTEK TRADING LLC"
	accounts = [
		"1-03-01-01 - Stock-in-Trade - KSA",
		"1-03-01-03 - Demo Stock - KSA",
	]

	# Sanity checks — skip silently if the environment doesn't match
	if not frappe.db.exists("Company", company):
		print(f"[repost_ksa_stock_gl_v2] Company {company} not found, skipping")
		return

	for account in accounts:
		if not frappe.db.exists("Account", account):
			print(f"[repost_ksa_stock_gl_v2] Account {account} not found, skipping")
			return

	# Step 1: Delete ALL GL entries on both stock accounts (active and cancelled)
	for account in accounts:
		frappe.db.sql(
			"""
			DELETE FROM `tabGL Entry`
			WHERE company = %s AND account = %s
			""",
			(company, account),
		)
		print(f"[repost_ksa_stock_gl_v2] Deleted GL entries on {account}")

	# Step 2: Get all SLE vouchers for this company
	sle_vouchers = frappe.db.sql(
		"""
		SELECT DISTINCT voucher_type, voucher_no, posting_date
		FROM `tabStock Ledger Entry`
		WHERE company = %s AND is_cancelled = 0
		ORDER BY posting_date, posting_time
		""",
		(company,),
		as_dict=True,
	)

	print(f"[repost_ksa_stock_gl_v2] Found {len(sle_vouchers)} vouchers to repost")

	# Step 3: For each voucher, regenerate GL entries via its own make_gl_entries method
	count = 0
	errors = 0
	for v in sle_vouchers:
		try:
			doc = frappe.get_doc(v.voucher_type, v.voucher_no)
			if doc.docstatus != 1:
				continue
			if hasattr(doc, "make_gl_entries"):
				doc.make_gl_entries(gl_entries=None, from_repost=True)
				count += 1
		except Exception as e:
			errors += 1
			frappe.log_error(
				title=f"GL regen failed v2: {v.voucher_type}/{v.voucher_no}",
				message=str(e)[:500],
			)

	frappe.db.commit()
	print(f"[repost_ksa_stock_gl_v2] Regenerated GL for {count} vouchers, {errors} errors")
