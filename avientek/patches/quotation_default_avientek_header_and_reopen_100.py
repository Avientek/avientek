"""#0563 + #0565 data step (Sammish 2026-10-14). Idempotent.

#0563: draft and Open quotations that still carry their company's default
letter head get "Avientek Header" (the new quotation default).

#0565: 2026 quotations at 100% probability that ERPNext's daily job marked
"Expired" (no Sales Order yet) go back to "Open" so the dispatch team sees
them under the Open filter. From now on such quotes are not expired (see
avientek/__init__.py _patch_quotation_expiry_skips_100). 2025 ones are left
as they are (agreed).
"""
import frappe


def execute():
	if frappe.db.exists("Letter Head", "Avientek Header"):
		frappe.db.sql(
			"""UPDATE `tabQuotation` q
			   JOIN `tabCompany` c ON c.name = q.company
			   SET q.letter_head = 'Avientek Header'
			   WHERE (q.docstatus = 0 OR (q.docstatus = 1 AND q.status = 'Open'))
			     AND (IFNULL(q.letter_head, '') = ''
			          OR q.letter_head = c.default_letter_head)"""
		)

	frappe.db.sql(
		"""UPDATE `tabQuotation`
		   SET status = 'Open'
		   WHERE docstatus = 1 AND status = 'Expired'
		     AND probabilities = %s
		     AND transaction_date >= '2026-01-01'""",
		("100%",),
	)
