"""Clear NEGATIVE batch balances by generating DRAFT Stock Reconciliations
(TSK-2026-00698 / TSK-2026-00699).

Human-reviewed by design: this ONLY creates DRAFTS (docstatus 0), grouped by
company, each row setting the offending batch+warehouse to qty 0. Accounts
reviews and SUBMITS them (financial writes stay human-approved). Never submits.

    # dry-run (default): show what would be created
    bench --site <site> execute avientek.scripts.draft_negative_batch_reconciliations.run
    # create drafts:
    bench --site <site> execute avientek.scripts.draft_negative_batch_reconciliations.run \
        --kwargs "{'apply': True}"
    # one company only:
    ... --kwargs "{'company': 'Avientek FZCO', 'apply': True}"
"""
import frappe
from frappe.utils import flt, nowdate, nowtime
from avientek.events.negative_batch_balance import find_negative_batch_balances


def _valuation_rate(item, warehouse):
    # Target qty is 0 (value 0), but provide a sensible rate for the row.
    rate = frappe.db.get_value("Bin", {"item_code": item, "warehouse": warehouse}, "valuation_rate")
    if not flt(rate):
        rate = frappe.db.get_value(
            "Bin", {"item_code": item, "valuation_rate": [">", 0]}, "valuation_rate"
        )
    if not flt(rate):
        rate = frappe.db.get_value("Item", item, "valuation_rate")
    return flt(rate) or 0.0


def run(company=None, apply=False, max_rows=500):
    rows = find_negative_batch_balances(company)
    if not rows:
        print("No negative batch balances found. Nothing to do.")
        return []
    if len(rows) > max_rows:
        print(f"WARNING: {len(rows)} negatives exceed max_rows={max_rows}; capping. "
              f"Raise max_rows to handle all.")
        rows = rows[:max_rows]

    # group by company (each Stock Reconciliation is single-company)
    by_company = {}
    for r in rows:
        item = frappe.db.get_value("Batch", r.batch_no, "item")
        by_company.setdefault(r.company, []).append(
            {
                "item_code": item,
                "warehouse": r.warehouse,
                "qty": 0,
                "valuation_rate": _valuation_rate(item, r.warehouse),
                "use_serial_batch_fields": 1,
                "batch_no": r.batch_no,
                "_current": flt(r.qty, 3),
            }
        )

    created = []
    for comp, items in by_company.items():
        print(f"\n=== {comp}: {len(items)} negative batch row(s) -> Stock Reconciliation ===")
        for it in items:
            print(f"   {it['batch_no']} @ {it['warehouse']} : {it['_current']} -> 0 "
                  f"(rate {it['valuation_rate']})")
        if not apply:
            continue
        doc = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "purpose": "Stock Reconciliation",
            "company": comp,
            "set_posting_time": 1,
            "posting_date": nowdate(),
            "posting_time": nowtime(),
            "items": [
                {k: v for k, v in it.items() if not k.startswith("_")} for it in items
            ],
        })
        doc.insert(ignore_permissions=True)   # DRAFT only — never submit
        created.append(doc.name)
        print(f"   -> created DRAFT {doc.name}")

    if apply:
        frappe.db.commit()
        print(f"\nCreated {len(created)} draft Stock Reconciliation(s): {created}")
        print("REVIEW and SUBMIT them in the Stock Reconciliation list (Accounts).")
    else:
        print(f"\nDRY-RUN: would create {len(by_company)} draft(s) across "
              f"{sum(len(v) for v in by_company.values())} row(s). Pass apply=True to create.")
    return created
