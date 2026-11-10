"""SUP: approved quotes opened a blank Sales Order.

Quote lines carried ordered_qty although no Sales Order was ever made against
the quote (copied from an already-ordered quote). ERPNext then mapped no lines.
Recompute ordered_qty from submitted Sales Order lines ONLY for submitted quotes
that no submitted Sales Order references at all, so quotes ordered the normal
way are never touched. Idempotent.
"""
import frappe


def execute():
	rows = frappe.db.sql(
		"""SELECT qi.name, qi.parent
		   FROM `tabQuotation Item` qi
		   JOIN `tabQuotation` q ON q.name = qi.parent
		   WHERE q.docstatus = 1 AND q.status NOT IN ('Ordered', 'Lost')
		     AND IFNULL(qi.ordered_qty, 0) > 0
		     AND NOT EXISTS (SELECT 1 FROM `tabSales Order Item` a
		                     WHERE a.prevdoc_docname = q.name AND a.docstatus = 1)
		     AND NOT EXISTS (SELECT 1 FROM `tabSales Order Item` b
		                     WHERE b.quotation_item = qi.name AND b.docstatus = 1)""",
		as_dict=True,
	)
	for r in rows:
		frappe.db.set_value("Quotation Item", r.name, "ordered_qty", 0, update_modified=False)
	if rows:
		print(f"reset ordered_qty on {len(rows)} lines of {len({r.parent for r in rows})} quotations")
