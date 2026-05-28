"""Add Quotation.submitted_probability Custom Field + backfill.

Sridhar 2026-05-28 (Probability BRD popup bug): the JS popup compared
the new value against the LAST SAVED probability instead of the
probability captured at submission time. After a user downgraded from
75%→10% and saved, the baseline became 10% — subsequent edits didn't
fire the popup because 10→anything doesn't satisfy "old ≥ 75%".

BRD intent: the "original probability at the time of submission" is
the eternal baseline.
  - If submitted at <75%: all post-submit edits are FREE.
  - If submitted at ≥75%: any downgrade to <75% needs approval, on
    every attempt, regardless of intermediate state.

Fix: new Custom Field `submitted_probability` (Data, read_only,
allow_on_submit=0) captured on the `on_submit` event and never
modified again. JS + server validator both compare against this
field.

Backfills existing submitted Quotations using their CURRENT
`probabilities` value (best-effort — we have no historical record of
what they were submitted with, but if they haven't been downgraded
yet the current value IS the submission value).

Idempotent.
"""
import frappe


FIELD = "Quotation-submitted_probability"


def execute():
	if not frappe.db.exists("Custom Field", FIELD):
		cf = frappe.new_doc("Custom Field")
		cf.dt = "Quotation"
		cf.fieldname = "submitted_probability"
		cf.label = "Submitted Probability"
		cf.fieldtype = "Data"
		cf.read_only = 1
		cf.allow_on_submit = 0
		cf.hidden = 1
		cf.insert_after = "probabilities"
		cf.description = (
			"Frozen at submit time. Holds the probability the document was "
			"originally submitted with — used as the eternal baseline by the "
			"post-submit approval popup. Never modified after on_submit."
		)
		cf.insert(ignore_permissions=True)
		print(f"[add_submitted_probability_field] Created {FIELD}")

	# Backfill — for submitted Quotations without submitted_probability, copy
	# current probabilities. Best-effort; the only safer alternative would be
	# to walk Version history which is rarely complete for legacy data.
	rows = frappe.db.sql(
		"""
		SELECT name, probabilities
		FROM `tabQuotation`
		WHERE docstatus = 1
		  AND (submitted_probability IS NULL OR submitted_probability = '')
		  AND probabilities IS NOT NULL AND probabilities != ''
		""",
		as_dict=True,
	)
	for r in rows:
		frappe.db.set_value(
			"Quotation", r["name"], "submitted_probability", r["probabilities"],
			update_modified=False,
		)
	if rows:
		frappe.db.commit()
	print(f"[add_submitted_probability_field] Backfilled {len(rows)} submitted Quotations")
