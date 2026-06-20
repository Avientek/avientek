import frappe
from frappe import _
from frappe.model.document import Document


class PRFApprovalRule(Document):
    def validate(self):
        self._validate_chain_ordering()
        self._validate_amount_range()
        self._validate_date_range()

    def _validate_chain_ordering(self):
        if not self.approval_chain:
            frappe.throw(_("Approval Chain must have at least one level."))
        levels = [int(row.level or 0) for row in self.approval_chain]
        if any(l <= 0 for l in levels):
            frappe.throw(_("Approval Chain levels must be positive integers."))
        if len(levels) > 5:
            frappe.throw(_("Max 5 levels per approval chain."))
        if sorted(levels) != list(range(1, len(levels) + 1)):
            frappe.throw(
                _("Approval Chain levels must be consecutive starting at 1 (1, 2, 3, ...). Got: {0}").format(levels)
            )

    def _validate_amount_range(self):
        if (self.amount_from or 0) and (self.amount_to or 0):
            if float(self.amount_from) > float(self.amount_to):
                frappe.throw(_("Amount From cannot be greater than Amount To."))

    def _validate_date_range(self):
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            frappe.throw(_("Valid From cannot be after Valid To."))
