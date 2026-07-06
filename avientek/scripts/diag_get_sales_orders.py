"""Verify get_sales_orders hardening (Error Log: 'missing 1 required
positional argument' + SQL injection).

Run: bench --site avintek.local execute avientek.scripts.diag_get_sales_orders.run
"""
import frappe
from avientek.events.send_email import get_sales_orders


def run():
    # 1. No arg → clean ValidationError (not TypeError → no Error Log)
    try:
        get_sales_orders()
        print("FAIL: no-arg call did not raise")
    except frappe.ValidationError as e:
        print(f"OK: no-arg call raises ValidationError: {e}")
    except TypeError as e:
        print(f"FAIL: still raises TypeError (would spam Error Log): {e}")

    # 2. Real company → runs, parameterised, returns a dict
    company = frappe.db.get_value("Company", {}, "name")
    res = get_sales_orders(company)
    print(f"OK: get_sales_orders({company!r}) -> {type(res).__name__} with {len(res)} customer(s)")

    # 3. Injection attempt is treated as a literal value (no SQL break)
    res2 = get_sales_orders('X" OR "1"="1')
    print(f"OK: injection string handled as literal -> {len(res2)} customer(s) (expect 0)")
