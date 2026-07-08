"""ERP-TKT-42: Quote Module slow / hangs. Server-side probe — time the
calculation pipeline + validate hooks on the largest quotes and count DB
queries to spot an N+1 / hotspot. (Client-side render is separate; this
isolates the server contribution.)

Run: bench --site avintek.local execute avientek.scripts.diag_quote_perf.run
"""
import time
import frappe


def _time_block(label, fn):
    frappe.db.sql("SET @x=0")  # noop to ensure connection
    n0 = frappe.db.sql("SHOW SESSION STATUS LIKE 'Questions'")[0][1]
    t0 = time.monotonic()
    try:
        fn()
        err = ""
    except Exception as e:
        err = f" ERROR: {type(e).__name__}: {str(e)[:80]}"
    dt = (time.monotonic() - t0) * 1000
    n1 = frappe.db.sql("SHOW SESSION STATUS LIKE 'Questions'")[0][1]
    print(f"  {label:34} {dt:8.0f} ms   ~{int(n1)-int(n0):5} queries{err}")


def run():
    big = frappe.db.sql("""
        SELECT parent, COUNT(*) c FROM `tabQuotation Item`
        GROUP BY parent ORDER BY c DESC LIMIT 3""", as_dict=True)
    print("Largest quotes by item count:", [(r.parent, r.c) for r in big])
    if not big:
        return
    for row in big:
        name = row.parent
        print(f"\n=== {name} ({row.c} items) ===")
        _time_block("get_doc (load)", lambda: frappe.get_doc("Quotation", name))
        doc = frappe.get_doc("Quotation", name)

        from avientek.events import quotation as q
        for fn_name in ("run_calculation_pipeline", "rebuild_brand_summary",
                        "validate_item_tax_template", "validate_margin_approval_required"):
            fn = getattr(q, fn_name, None)
            if fn:
                _time_block(fn_name, lambda fn=fn: fn(doc))

        # permission query cost (RBAC) for a restricted-ish user
        _time_block("customer_permission_query build",
                    lambda: __import__("avientek.api.quotation_access", fromlist=["customer_permission_query"]).customer_permission_query("Administrator"))
    frappe.db.rollback()
