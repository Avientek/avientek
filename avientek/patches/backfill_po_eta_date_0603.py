"""#0603: restore the ETA Date on Purchase Order lines where it was lost.

"Set SO ETA" recorded the date in the line's ETA History but did not save it
on the line itself (see purchase_order.update_eta). Where a line has no ETA
Date, take the latest date found in its own history. A blank entry after a
dated one is the same bug (the button was pressed again after the date had
vanished), so the latest DATED entry is used. Lines that have a date are not
touched; the PO's modified date is left alone. Idempotent.
"""
import json

import frappe
from frappe.utils import getdate


def execute():
	if not frappe.db.has_column("Purchase Order Item", "eta"):
		return
	rows = frappe.db.sql(
		"""SELECT name, eta_history FROM `tabPurchase Order Item`
		   WHERE eta IS NULL AND docstatus < 2 AND eta_history LIKE %s""",
		('%"eta_date": "2%',), as_dict=True,
	)
	done = 0
	for r in rows:
		try:
			history = json.loads(r.eta_history or "[]")
		except ValueError:
			continue
		dated = [h.get("eta_date") for h in history if isinstance(h, dict) and h.get("eta_date")]
		if not dated:
			continue
		try:
			eta = getdate(dated[-1])
		except Exception:
			continue
		frappe.db.set_value("Purchase Order Item", r.name, "eta", eta, update_modified=False)
		done += 1
	if done:
		print(f"[#0603] ETA Date restored on {done} Purchase Order lines")
