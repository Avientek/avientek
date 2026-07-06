"""Verify the auto-assign fix (Rahul 2026-07-06):
  1. _assign_todo is a no-op while enable_quotation_assignment is off.
  2. _resolve_approvers_for_quote excludes users whose Company UP excludes
     the quote's company (pd@ scoped to India must NOT resolve for a FZCO quote,
     but MUST still resolve for an India-company quote).

Run: bench --site avintek.local execute avientek.scripts.diag_approver_assign.run
"""
import frappe
from avientek.events import quotation_notifications as qn


def _companies():
    return frappe.get_all("Company", pluck="name")


def run():
    print("Companies:", _companies())
    india = "Avientek Electronics Trading PVT. LTD"
    # find a real free-zone company name
    fzco = next((c for c in _companies() if "FZCO" in c.upper() or "FZE" in c.upper()), None)
    print("FZCO company detected:", fzco)

    cfg_roles = ("GM-CS",)  # L1 approver role

    def resolve(company):
        doc = frappe._dict(
            doctype="Quotation",
            name="TEST-RESOLVE",
            company=company,
            sales_person="",  # no sales person → tests company gate + sees-everyone path
            sales_team=[],
            get=lambda k, d=None: {"company": company, "sales_person": "", "sales_team": []}.get(k, d),
        )
        return qn._resolve_approvers_for_quote(doc, cfg_roles)

    for company in filter(None, [fzco, india]):
        matched = resolve(company)
        has_pd = "pd@avientek.com" in matched
        print(f"\n[{company}] resolved={len(matched)} pd@_included={has_pd}")
        print("  members:", sorted(matched))

    # 2. _assign_todo no-op check
    has_field = frappe.get_meta("Avientek Settings").has_field("enable_quotation_assignment")
    setting = (
        frappe.db.get_single_value("Avientek Settings", "enable_quotation_assignment")
        if has_field
        else None
    )
    print(f"\nfield_exists={has_field} enable_quotation_assignment={setting!r} (absent/None/0 => disabled)")
    before = frappe.db.count("ToDo")
    qn._assign_todo(
        frappe._dict(doctype="Quotation", name="TEST-NOOP"),
        "pd@avientek.com",
        "should NOT create a todo",
    )
    after = frappe.db.count("ToDo")
    print(f"ToDo count before={before} after={after} (equal => _assign_todo is a no-op)")
    frappe.db.rollback()
