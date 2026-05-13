"""Re-point the 3 Quotation approval Number Cards to the V3 workflow
state names so GM-CS / GM users see the correct counts on Sales Team
workspace.

Sammish 2026-05-15. Why this exists:
  - V2 workflow used states "Pending Level 1 Approval" / "Pending Level
    2 Approval".
  - Yesterday's V3 upgrade renamed them to "Pending For Approval" (L1)
    and "Pending L2 Approval" (L2). The Number Card filters_json was
    never updated → counts always read 0 (or just the 27 stuck V2
    quotes), so GM-CS users reported the card as "not visible / not
    working".

Fix:
  - Update filters_json on 3 cards to filter on BOTH new V3 states AND
    the legacy V2 state names. Legacy names stay because there are 27
    quotes still stuck in V2 states that need bridge-transition
    approval — they should remain visible until cleared.

Idempotent. Re-running just rewrites the same filter blob.

The repo JSON files at avientek/avientek/number_card/<name>/<name>.json
are the source of truth; bench migrate re-imports them. This patch is
a belt-and-braces immediate fix in case migrate is queued.
"""
import frappe


UPDATES = {
	"Pending Level 1 Approvals": (
		'[["Quotation","workflow_state","in",'
		'["Pending For Approval","Pending Level 1 Approval"]]]'
	),
	"Pending Level 2 Approvals": (
		'[["Quotation","workflow_state","in",'
		'["Pending L2 Approval","Pending Level 2 Approval"]]]'
	),
	"My Quotes Pending Approval": (
		'[["Quotation","workflow_state","in",'
		'["Pending For Approval","Pending L2 Approval",'
		'"Pending Level 1 Approval","Pending Level 2 Approval"]]]'
	),
}


def execute():
	for card_name, filters_json in UPDATES.items():
		if not frappe.db.exists("Number Card", card_name):
			print(f"[repoint_quotation_approval_cards_to_v3] skip — {card_name!r} does not exist")
			continue
		current = frappe.db.get_value("Number Card", card_name, "filters_json")
		if current == filters_json:
			print(f"[repoint_quotation_approval_cards_to_v3] up-to-date: {card_name}")
			continue
		frappe.db.set_value(
			"Number Card", card_name, "filters_json", filters_json,
			update_modified=False,
		)
		print(f"[repoint_quotation_approval_cards_to_v3] updated {card_name}")

	frappe.db.commit()
	frappe.clear_cache()
