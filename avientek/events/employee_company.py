"""#0594 (Jithin 2026-11-12): an employee can only be used on transactions of
their own company.

Employee payments and claims were being booked against employees of another
Avientek company (e.g. FZCO employees on L.L.C Journal Entries and PRFs), which
Accounts wants stopped. The one exception is an employee who moved between the
two companies through an Employee Transfer, so the old and the new company both
stay valid for that employee.

Applied on validate of Expense Claim, Employee Advance, Payment Entry, Journal
Entry (every employee line) and Payment Request Form. The PRF Party picker
already lists only the PRF company's employees.
"""

import frappe
from frappe import _


def allowed_companies(employee):
    """The employee's company plus both sides of any submitted Employee Transfer."""
    companies = {frappe.db.get_value("Employee", employee, "company")}
    for t in frappe.get_all("Employee Transfer", filters={"employee": employee, "docstatus": 1},
                            fields=["company", "new_company"]):
        companies.update((t.company, t.new_company))
    companies.discard(None)
    return companies


def _check(employee, company, where):
    if not employee or not company:
        return
    allowed = allowed_companies(employee)
    if allowed and company not in allowed:
        frappe.throw(
            _("{0}: employee {1} belongs to {2}, not {3}. Use an employee of {3}, "
              "or record an Employee Transfer first.").format(
                where, frappe.bold(employee), ", ".join(sorted(allowed)), frappe.bold(company)),
            title=_("Employee of Another Company"),
        )


def validate_employee_company(doc, method=None):
    if doc.doctype in ("Expense Claim", "Employee Advance"):
        _check(doc.get("employee"), doc.company, _("Employee"))
    elif doc.doctype in ("Payment Entry", "Payment Request Form"):
        if doc.get("party_type") == "Employee":
            _check(doc.get("party"), doc.company, _("Party"))
    elif doc.doctype == "Journal Entry":
        for row in doc.get("accounts") or []:
            if row.get("party_type") == "Employee":
                _check(row.get("party"), doc.company, _("Row {0}").format(row.idx))
