"""Ghost Voucher Repost Log — one row per ghost voucher tracked through cleanup.

Built by patch `audit_ghost_vouchers_export_csv` (creates Pending Review rows).
Accounts reviews + ticks `ready_for_repost` per row.
Patch `repost_ghost_vouchers_bulk` processes only Ready rows.
"""
import frappe
from frappe.model.document import Document


class GhostVoucherRepostLog(Document):
	pass
