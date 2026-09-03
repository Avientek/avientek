"""Verify the #0526 company-guard patch on the standard Batch-Wise Balance
History report (the base of the customer's 'Batch-Wise Ageing Report').

    bench --site avintek.local execute \
        avientek.scripts.verify_bwbh_company_guard.run
"""
import frappe
from erpnext.stock.report.batch_wise_balance_history import batch_wise_balance_history as bwbh

CO = "Avientek FZCO"
FROM, TO = "2026-01-01", "2026-09-03"


def _run(label, filters):
    try:
        cols, data = bwbh.execute(frappe._dict(filters))
        whs = sorted({r[3] for r in data})
        print(f"[{label}] OK rows={len(data)} warehouses={len(whs)}")
        return len(data), whs
    except frappe.ValidationError as e:
        print(f"[{label}] THROW: {e}")
        return None, None


def run():
    print("SLE estimate:", frappe.db.estimate_count("Stock Ledger Entry"), "| LIMIT:", bwbh.SLE_COUNT_LIMIT)
    print("patched execute in place:", bwbh.execute.__name__ == "_patched_execute")

    n_co, whs_co = _run("1 company-only (should RETURN rows now)", {"company": CO, "from_date": FROM, "to_date": TO})
    _run("2 no-scope filter (guard must STILL throw)", {"from_date": FROM, "to_date": TO})
    n_ft, whs_ft = _run("3 warehouse_type=Freezed Items (must still narrow)",
                        {"company": CO, "warehouse_type": "Freezed Items", "from_date": FROM, "to_date": TO})

    if whs_co is not None:
        print("\ncompany-only distinct warehouses:", len(whs_co))
        print(whs_co)
    if whs_co and whs_ft is not None:
        print("\nnarrowing sane (freezed subset <= company):",
              len(whs_ft), "<=", len(whs_co), "=", len(whs_ft) <= len(whs_co))

    # end-to-end via the customer's actual Custom Report
    from frappe.desk.query_report import run as qr_run
    try:
        res = qr_run("Batch-Wise Ageing Report", filters={"company": CO, "from_date": FROM, "to_date": TO})
        rows = res.get("result", [])
        whs = sorted({(r[3] if isinstance(r, (list, tuple)) else r.get("warehouse")) for r in rows})
        print(f"\n[4 Custom Report 'Batch-Wise Ageing Report' end-to-end] rows={len(rows)} warehouses={len(whs)}")
    except Exception as e:
        print("\n[4 Custom Report] ERROR:", repr(e))
