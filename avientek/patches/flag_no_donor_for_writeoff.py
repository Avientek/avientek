"""Patch A4 — finalise WRITE_OFF rows for Stores Manager attention.

Sets status='Pending' on every Plan row where path=WRITE_OFF AND
status in (None, '', 'Pending'). Logs a remark explaining what the
Stores Manager / Accounts team should do next.

This patch does NOT auto-create Stock Reconciliation or any GL-touching
operation for WRITE_OFF rows — those require human judgement (physical
count vs system count, write-off expense GL impact, etc.).

Idempotent. Safe to re-run.
"""
import frappe


WRITEOFF_REMARK = (
	"No donor batch found in this warehouse with sufficient surplus. "
	"Manual action required:\n"
	"  1. Stores Manager physically counts the item in this warehouse.\n"
	"  2. Compare physical count to system Bin total.\n"
	"  3. If physical < system: Stock Reconciliation at actual val_rate "
	"(Accounts approval — has GL impact).\n"
	"  4. If physical = system (pure attribution error): Stock "
	"Reconciliation at val_rate=0 + this batch set to 0 in same SR. "
	"Then update this Plan row status=Done with remarks."
)


def execute():
	rows = frappe.get_all(
		"Negative Batch Cleanup Plan",
		filters=[
			["path", "=", "WRITE_OFF"],
			["status", "in", ["", "Pending"]],
		],
		fields=["name"],
	)
	print(f"[flag_no_donor_for_writeoff] {len(rows)} WRITE_OFF rows to flag")

	touched = 0
	for r in rows:
		doc = frappe.get_doc("Negative Batch Cleanup Plan", r["name"])
		if not doc.remarks or "Manual action required" not in (doc.remarks or ""):
			doc.remarks = WRITEOFF_REMARK
			doc.save(ignore_permissions=True)
			touched += 1

	frappe.db.commit()
	print(f"[flag_no_donor_for_writeoff] touched={touched}")
