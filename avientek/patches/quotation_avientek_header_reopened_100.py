"""#0563 follow-up (Sammish 2026-10-14). Idempotent.

quotation_default_avientek_header_and_reopen_100 switched letter heads BEFORE
reopening the 2026 expired 100% quotes, so the 113 reopened (now Open) quotes
kept their company letter head. Re-apply the same rule: draft and Open
quotations still on the company default (or blank) get "Avientek Header".
Display-only field; written directly so old quotes are not re-validated.
"""
import frappe


def execute():
	if not frappe.db.exists("Letter Head", "Avientek Header"):
		return
	frappe.db.sql(
		"""UPDATE `tabQuotation` q
		   JOIN `tabCompany` c ON c.name = q.company
		   SET q.letter_head = 'Avientek Header'
		   WHERE (q.docstatus = 0 OR (q.docstatus = 1 AND q.status = 'Open'))
		     AND (IFNULL(q.letter_head, '') = ''
		          OR q.letter_head = c.default_letter_head)"""
	)
