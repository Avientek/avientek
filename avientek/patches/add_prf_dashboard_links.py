"""Add DocType Link records so the Connections section on Purchase
Order, Sales Order, Sales Invoice, Purchase Invoice, Journal Entry,
Payment Entry, and Delivery Note lists the Payment Request Forms that
reference them.

PRF stores its references in the child table `Payment Request
Reference` (parent table = `payment_references` on PRF). Each child
row carries `reference_doctype` + `reference_name`. To make Frappe's
Connections dashboard show "Payment Request Form" cards under a PO
(or SO / SI / etc.), we add a DocType Link entry on the source
doctype pointing to Payment Request Form via the
`Payment Request Reference` child table.

Jithin 2026-05-13: this is the "Connection dashboard - yes you can
add the connected documents under the Connection dashboard" ask.

Idempotent. Safe to re-run.
"""
import frappe


PRF_DOCTYPE = "Payment Request Form"
CHILD_DOCTYPE = "Payment Request Reference"
CHILD_TABLE_FIELDNAME = "payment_references"
GROUP_LABEL = "Payments"

# Sammish 2026-05-16 (Jithin #8): walk BOTH link fields on the child
# table — `reference_name` AND `document_reference`. Why both:
#   - reference_name stores the legacy pointer for SO / SI / PO / JV /
#     PE / DN (= Frappe doc name) but for Purchase Invoice / Debit Note
#     it stores the supplier's free-text bill_no (e.g. "#032079"), so a
#     lookup keyed on the PI's Frappe doc name finds nothing.
#   - document_reference is the canonical Frappe doc pointer set by
#     the picker post 2026-05-09 for every type.
# Adding both Link rows lets Frappe's Connections panel find PRFs
# regardless of which field has the matching value.
LINK_FIELDNAMES = ["reference_name", "document_reference"]

# Source doctypes that should show linked PRFs under their Connections.
SOURCE_DOCTYPES = [
	"Purchase Order",
	"Sales Order",
	"Sales Invoice",
	"Purchase Invoice",
	"Journal Entry",
	"Payment Entry",
	"Delivery Note",
]


def execute():
	if not frappe.db.exists("DocType", PRF_DOCTYPE):
		print(f"[add_prf_dashboard_links] {PRF_DOCTYPE} missing — skipping")
		return

	added = 0
	already = 0
	skipped = 0
	for source in SOURCE_DOCTYPES:
		if not frappe.db.exists("DocType", source):
			skipped += 1
			print(f"[add_prf_dashboard_links] {source}: DocType missing — skipping")
			continue
		dt = frappe.get_doc("DocType", source)

		# Track which link_fieldnames already exist so we only append
		# the missing ones (idempotent across both old and new schema).
		existing_fields = set()
		for row in dt.get("links") or []:
			if (
				row.link_doctype == PRF_DOCTYPE
				and (row.get("parent_doctype") or "") == PRF_DOCTYPE
				and (row.get("table_fieldname") or "") == CHILD_TABLE_FIELDNAME
				and row.link_fieldname in LINK_FIELDNAMES
			):
				existing_fields.add(row.link_fieldname)

		missing = [fn for fn in LINK_FIELDNAMES if fn not in existing_fields]
		if not missing:
			already += 1
			print(f"[add_prf_dashboard_links] {source}: both PRF links already present")
			continue

		for fn in missing:
			dt.append("links", {
				# "table_fieldname" + "parent_doctype" tell Frappe to walk
				# the child table on the parent doctype (PRF) and surface
				# every parent (PRF) whose child's `<fn>` matches the
				# current source doc's name.
				"link_doctype": PRF_DOCTYPE,
				"link_fieldname": fn,
				"parent_doctype": PRF_DOCTYPE,
				"table_fieldname": CHILD_TABLE_FIELDNAME,
				"group": GROUP_LABEL,
			})
		try:
			dt.flags.ignore_validate = True
			dt.flags.ignore_permissions = True
			dt.save()
			added += 1
			print(
				f"[add_prf_dashboard_links] {source}: added PRF links via {missing}"
			)
		except Exception:
			frappe.log_error(
				title=f"add_prf_dashboard_links: save failed for {source}",
				message=frappe.get_traceback(),
			)
	frappe.db.commit()
	print(
		f"[add_prf_dashboard_links] done — added={added} "
		f"already={already} skipped={skipped}"
	)
