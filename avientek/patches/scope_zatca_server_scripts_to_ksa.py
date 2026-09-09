"""Scope the ZATCA Sales-Invoice Server Scripts to Saudi Arabia companies only.

SUP-2026-00045 / INV-LLC-26-01134 (Avientek Electronics Trading L.L.C, UAE):
VAT showed wrong and the invoice could not be submitted ("Debit and Credit not
equal ... Difference is -14.82").

Root cause: two DB-stored Server Scripts on Sales Invoice —
`fix_zatca_vat_rate_zero` (Before Save) and `ZATCA-Tax-Rounding-Fix`
(Before Submit) — implement Saudi e-invoicing (ZATCA / BR-CO-14/15/17) rules but
run on EVERY Sales Invoice with no company scoping. On an invoice with
`apply_discount_on = "Grand Total"`, ERPNext leaves the tax ROW at the gross
amount (5% of the undiscounted base) while `total_taxes_and_charges` holds the
tax net of the grand-total discount's share. `fix_zatca_vat_rate_zero` treats the
gross row as "wrong", rewrites it to the net figure and then subtracts that delta
AGAIN from `total_taxes_and_charges` / `grand_total` — understating VAT by the
discount's tax share (15.00 here) and breaking the GL balance on submit.
`ZATCA-Tax-Rounding-Fix` additionally flips `apply_discount_on` from
"Grand Total" to "Net Total" on any discounted invoice.

Fix: wrap each script body in a Saudi-Arabia company guard so the ZATCA logic
runs only for KSA companies (where it belongs and where it is already live). For
every non-KSA company the scripts become a no-op and ERPNext's own, correct tax
calculation stands. KSA behaviour is unchanged. Idempotent — re-running skips a
script that already carries the guard.
"""
import frappe

GUARD_MARKER = "KSA_COMPANY_GUARD"
GUARD_HEAD = (
    "# " + GUARD_MARKER + ": ZATCA / BR-CO-14/15/17 rules apply only to Saudi\n"
    "# Arabia companies. On non-KSA invoices this corrupts VAT on\n"
    "# discount-on-Grand-Total invoices (SUP-2026-00045 / INV-LLC-26-01134),\n"
    "# understating tax and breaking the GL balance on submit. Scope to KSA.\n"
    'if frappe.db.get_value("Company", doc.company, "country") == "Saudi Arabia":\n'
)

SCRIPTS = ("fix_zatca_vat_rate_zero", "ZATCA-Tax-Rounding-Fix")


def _wrap(script):
    body = "\n".join(("    " + ln) if ln.strip() else ln for ln in script.splitlines())
    return GUARD_HEAD + body + "\n"


def execute():
    for name in SCRIPTS:
        if not frappe.db.exists("Server Script", name):
            continue
        script = frappe.db.get_value("Server Script", name, "script") or ""
        if GUARD_MARKER in script:
            continue  # already scoped
        frappe.db.set_value("Server Script", name, "script", _wrap(script))
        frappe.logger().info(f"Scoped Server Script '{name}' to Saudi Arabia companies")
    frappe.db.commit()
