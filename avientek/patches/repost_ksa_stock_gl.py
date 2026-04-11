"""One-time patch to fix Stock-in-Trade GL imbalance for AVIENTEK TRADING LLC.

Deletes all GL entries on the Stock-in-Trade account for KSA company and
triggers a fresh full repost from SLE to regenerate clean GL entries.
"""

import frappe


def execute():
	company = "AVIENTEK TRADING LLC"
	account = "1-03-01-01 - Stock-in-Trade - KSA"

	# Sanity checks — skip silently if the environment doesn't match
	if not frappe.db.exists("Company", company):
		print(f"[repost_ksa_stock_gl] Company {company} not found, skipping")
		return
	if not frappe.db.exists("Account", account):
		print(f"[repost_ksa_stock_gl] Account {account} not found, skipping")
		return

	# Step 1: Delete ALL GL entries on the stock account (active and cancelled)
	deleted = frappe.db.sql(
		"""
		DELETE FROM `tabGL Entry`
		WHERE company = %s AND account = %s
		""",
		(company, account),
	)
	print(f"[repost_ksa_stock_gl] Deleted GL entries on {account}")

	# Step 2: Cancel any previously submitted Repost Item Valuation entries
	# so we can create fresh ones without conflicts
	frappe.db.sql(
		"""
		UPDATE `tabRepost Item Valuation`
		SET status = 'Skipped'
		WHERE company = %s AND status IN ('Queued', 'Failed', 'In Progress')
		""",
		(company,),
	)

	# Step 3: Get all SLE vouchers for this company
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

	print(f"[repost_ksa_stock_gl] Found {len(sle_vouchers)} vouchers to repost")

	# Step 4: For each voucher, regenerate GL entries via its own make_gl_entries method
	count = 0
	errors = 0
	for v in sle_vouchers:
		try:
			doc = frappe.get_doc(v.voucher_type, v.voucher_no)
			if doc.docstatus != 1:
				continue
			# Most stock doctypes have make_gl_entries method
			if hasattr(doc, "make_gl_entries"):
				doc.make_gl_entries(gl_entries=None, from_repost=True)
				count += 1
		except Exception as e:
			errors += 1
			frappe.log_error(
				title=f"GL regen failed: {v.voucher_type}/{v.voucher_no}",
				message=str(e)[:500],
			)

	frappe.db.commit()
	print(f"[repost_ksa_stock_gl] Regenerated GL for {count} vouchers, {errors} errors")
