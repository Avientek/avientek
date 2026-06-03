"""Ghost Voucher Alert — silent detection log row written by the
post-submit verification hook when a submitted doc has missing GL/SLE.

No email side effects. Sridhar reviews the list on demand via
/app/ghost-voucher-alert.
"""
import frappe
from frappe.model.document import Document


class GhostVoucherAlert(Document):
	pass
