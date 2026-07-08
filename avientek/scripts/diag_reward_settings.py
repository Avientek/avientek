"""ERP-TKT-39: reward/incentive JV not getting passed for invoices linked to a
quote (ref QN-LLC-26-00460). Dump the config and REPLAY the booking decision
for a given SI or quote so the exact skip reason is visible.

  run                 -> settings + which companies are mapped
  why <SI name>       -> replay book decision for one Sales Invoice
  quote <QN name>     -> find SIs traceable to the quote and replay each

bench --site avintek.local execute avientek.scripts.diag_reward_settings.<fn> --args '["NAME"]'
"""
import frappe
from frappe.utils import flt
from avientek.events.sales_invoice_reward_incentive import (
    _load_settings, _resolve_quotation_for_si,
    _compute_quotationwise, _compute_itemwise, _SI_JV_FIELD,
)


def run():
    s = frappe.get_single("Avientek Settings")
    method = (s.get("reward_incentive_method") or "").strip()
    print("reward_incentive_method:", method or "(BLANK → feature OFF)")
    rows = s.get("reward_incentive_company_accounts") or []
    print(f"company account mappings: {len(rows)}")
    for r in rows:
        full = all([r.get("reward_expense_account"), r.get("reward_payable_account"),
                    r.get("incentive_expense_account"), r.get("incentive_payable_account")])
        print(f"  {r.get('company'):45} complete={full}")
    print("\nCompanies WITHOUT a complete mapping will silently skip the JV.")


def why(si_name):
    print(f"=== replay reward/incentive decision for SI {si_name} ===")
    if not frappe.db.exists("Sales Invoice", si_name):
        print("  SI does not exist"); return
    doc = frappe.get_doc("Sales Invoice", si_name)
    print(f"  company={doc.company} docstatus={doc.docstatus} is_return={doc.get('is_return')} "
          f"grand_total={doc.grand_total}")
    if doc.get(_SI_JV_FIELD):
        print(f"  -> already booked JV: {doc.get(_SI_JV_FIELD)}"); return
    if int(doc.get('is_return') or 0):
        print("  -> SKIP: is_return"); return
    settings = _load_settings(doc.company)
    if not settings:
        print(f"  -> SKIP: no complete settings/account-mapping for company '{doc.company}'"); return
    print(f"  settings OK (method={settings['method']})")
    quote = _resolve_quotation_for_si(doc)
    if not quote:
        sos = [it.get('sales_order') for it in doc.items if it.get('sales_order')]
        print(f"  -> SKIP: no Quotation traceable. SI-item sales_order links={sos or 'NONE'}")
        print("     (cause: SI not from SO, or SO Item.prevdoc_docname blank)")
        return
    print(f"  quote resolved: {quote.name} grand_total={quote.get('grand_total')} "
          f"reward_total={quote.get('custom_total_reward_new')} incentive_total={quote.get('custom_total_incentive_new')}")
    if settings['method'] == "Item Wise":
        r, i = _compute_itemwise(doc, quote)
    else:
        r, i = _compute_quotationwise(doc, quote)
    print(f"  computed reward={flt(r,2)} incentive={flt(i,2)}")
    if flt(r,2) <= 0 and flt(i,2) <= 0:
        print("  -> SKIP: both zero (quote has no reward/incentive amounts, or proportion 0)")
    else:
        print("  -> WOULD BOOK a JV. If none exists on prod, booking crashed — check Error Log.")


def quote(qn):
    print(f"=== SIs traceable to quote {qn} ===")
    rows = frappe.db.sql("""
        SELECT DISTINCT si.name FROM `tabSales Invoice` si
        JOIN `tabSales Invoice Item` sii ON sii.parent=si.name
        JOIN `tabSales Order Item` soi ON soi.parent=sii.sales_order
        WHERE soi.prevdoc_docname=%s AND si.docstatus=1
    """, qn, pluck=True)
    if not rows:
        print("  no submitted SIs trace to this quote via SO Item.prevdoc_docname")
        return
    for si in rows:
        why(si)
        print()
