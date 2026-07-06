"""ERP-TKT-41: confirm get_outstanding_reference_documents returns the PI's
bill_date as invoice_date and the PI's due_date as due_date (the data the
fixed 'Get Purchase Invoice' JS now consumes).

Run: bench --site avintek.local execute avientek.scripts.diag_prf_pi_dates.run
"""
import frappe
from avientek.avientek.doctype.payment_request_form.payment_request_form import (
    get_outstanding_reference_documents,
)


def run():
    # Find a submitted PI with outstanding + a bill_date that differs from
    # posting_date (so the fix is observable).
    pis = frappe.db.sql(
        """SELECT name, supplier, company, bill_date, posting_date, due_date, outstanding_amount
           FROM `tabPurchase Invoice`
           WHERE docstatus=1 AND outstanding_amount>0
             AND bill_date IS NOT NULL AND bill_date != posting_date
           ORDER BY modified DESC LIMIT 1""",
        as_dict=True,
    )
    if not pis:
        print("No outstanding PI with a distinct bill_date found — cannot demo.")
        return
    pi = pis[0]
    print(f"PI {pi.name}: bill_date={pi.bill_date} posting_date={pi.posting_date} "
          f"due_date={pi.due_date} supplier={pi.supplier}")

    rows = get_outstanding_reference_documents({
        "posting_date": str(pi.posting_date),
        "company": pi.company,
        "party": pi.supplier,
        "party_type": "Supplier",
        "reference_doctype": "Purchase Invoice",
        "payment_type": "Pay",
    })
    match = [r for r in (rows or []) if r.get("voucher_no") == pi.name]
    if not match:
        print(f"(PI not returned by fetch for this party — {len(rows or [])} rows returned)")
        return
    r = match[0]
    print(f"\nServer row for {pi.name}:")
    print(f"  invoice_date = {r.get('invoice_date')}  (expect bill_date {pi.bill_date})")
    print(f"  due_date     = {r.get('due_date')}  (expect PI due_date {pi.due_date})")
    print(f"  posting_date = {r.get('posting_date')}")
    ok = str(r.get("invoice_date")) == str(pi.bill_date) and str(r.get("due_date")) == str(pi.due_date)
    print(f"\n{'PASS' if ok else 'FAIL'}: invoice_date=bill_date and due_date=PI.due_date")
