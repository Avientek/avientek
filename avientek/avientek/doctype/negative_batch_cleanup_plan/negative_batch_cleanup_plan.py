"""Negative Batch Cleanup Plan — one row per (item, warehouse, batch) bucket
with current negative balance.

Built by patch `find_donor_batches_for_negative` and consumed by patch
`execute_negative_batch_repack`. Stores Manager / Accounts Manager mark
`ready_for_execution` per row to authorise the actual Repack on prod.
"""
import frappe
from frappe.model.document import Document


class NegativeBatchCleanupPlan(Document):
	pass
