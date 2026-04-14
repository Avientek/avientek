"""Fix GL entries for Payment Entry and Journal Entry for AVIENTEK TRADING LLC.

The full GL rebuild patch failed on PE and JE because their make_gl_entries()
has a different signature (no gl_entries parameter).
"""

import frappe


def execute():
	company = "AVIENTEK TRADING LLC"

	if not frappe.db.exists("Company", company):
		print(f"[pe_je_gl] Company {company} not found, skipping")
		return

	# Payment Entries
	pe_names = frappe.db.sql(
		"SELECT name FROM `tabPayment Entry` WHERE company = %s AND docstatus = 1 ORDER BY posting_date",
		company, pluck="name",
	)
	print(f"[pe_je_gl] Processing {len(pe_names)} Payment Entries...")
	pe_ok = pe_err = 0
	for i, name in enumerate(pe_names):
		try:
			doc = frappe.get_doc("Payment Entry", name)
			doc.make_gl_entries()
			pe_ok += 1
		except Exception:
			pe_err += 1
		if (i + 1) % 100 == 0:
			frappe.db.commit()
			print(f"[pe_je_gl] PE: {i+1}/{len(pe_names)} ({pe_ok} ok, {pe_err} errors)")
	frappe.db.commit()
	print(f"[pe_je_gl] PE done: {pe_ok} ok, {pe_err} errors")

	# Journal Entries
	je_names = frappe.db.sql(
		"SELECT name FROM `tabJournal Entry` WHERE company = %s AND docstatus = 1 ORDER BY posting_date",
		company, pluck="name",
	)
	print(f"[pe_je_gl] Processing {len(je_names)} Journal Entries...")
	je_ok = je_err = 0
	for i, name in enumerate(je_names):
		try:
			doc = frappe.get_doc("Journal Entry", name)
			doc.make_gl_entries()
			je_ok += 1
		except Exception:
			je_err += 1
		if (i + 1) % 100 == 0:
			frappe.db.commit()
			print(f"[pe_je_gl] JE: {i+1}/{len(je_names)} ({je_ok} ok, {je_err} errors)")
	frappe.db.commit()
	print(f"[pe_je_gl] JE done: {je_ok} ok, {je_err} errors")
	print(f"[pe_je_gl] TOTAL: PE {pe_ok}+{pe_err}, JE {je_ok}+{je_err}")
