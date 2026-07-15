# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class QuotationItemHistory(Document):
	def get_invalid_links(self, is_submittable=False):
		"""`document_id` is a Dynamic Link to the PRIOR quotation this item was
		copied from — an audit/history reference, not an active dependency.

		Frappe's cancelled-link check (BaseDocument.get_invalid_links) would
		otherwise block saving the CURRENT quotation with "Cannot link cancelled
		document" the moment that prior quote is cancelled — poisoning every
		later quote that references it in history. Core already exempts
		`amended_from` for the same reason; we extend that exemption to this
		history field. Rahul 2026-07-15: QN-LTD-26-02379-1 -> cancelled
		QN-LTD-26-02216.
		"""
		invalid_links, cancelled_links = super().get_invalid_links(is_submittable)
		cancelled_links = [c for c in cancelled_links if c[0] != "document_id"]
		return invalid_links, cancelled_links
