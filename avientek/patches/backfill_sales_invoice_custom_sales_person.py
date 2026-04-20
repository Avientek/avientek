"""Backfill Sales Invoice.custom_sales_person from the first Sales Team row.

Finance flagged that filtering by "Sales Person = MIDHUN" on the Sales
Invoice list view returned only 4 results even though MIDHUN was
allocated on 1,000+ invoices through the Sales Team child table. The
UI filter hits the parent-level custom_sales_person Link field, which
had been left blank on ~10,700 of the 10,779 submitted invoices
because nothing was populating it.

This patch walks every SI with a non-empty Sales Team and writes the
first non-empty sales_person value to custom_sales_person when that
parent field is blank or stale. Going forward the before_save hook
(sync_custom_sales_person) keeps them in step.

Idempotent — re-running is a no-op once fields are aligned.
"""

import frappe


BATCH = 500


def execute():
    # Pull one row per (SI parent, primary sales_person) — SQL over the
    # child table to avoid loading 10k+ docs into memory.
    # idx=1 is ERPNext's convention for the first Sales Team row.
    rows = frappe.db.sql(
        """
        SELECT DISTINCT st.parent AS name, st.sales_person AS sales_person
        FROM `tabSales Team` st
        INNER JOIN (
            SELECT parent, MIN(idx) AS min_idx
            FROM `tabSales Team`
            WHERE parenttype = 'Sales Invoice' AND IFNULL(sales_person, '') != ''
            GROUP BY parent
        ) first ON first.parent = st.parent AND first.min_idx = st.idx
        WHERE st.parenttype = 'Sales Invoice'
          AND IFNULL(st.sales_person, '') != ''
        """,
        as_dict=True,
    )
    print(f"[backfill_sales_invoice_custom_sales_person] candidates: {len(rows)}")

    updated = 0
    for i, row in enumerate(rows, 1):
        current = frappe.db.get_value("Sales Invoice", row.name, "custom_sales_person")
        if (current or "") == row.sales_person:
            continue
        frappe.db.set_value(
            "Sales Invoice", row.name, "custom_sales_person",
            row.sales_person, update_modified=False,
        )
        updated += 1
        if updated % BATCH == 0:
            frappe.db.commit()
            print(f"  committed {updated} so far")

    frappe.db.commit()
    print(f"[backfill_sales_invoice_custom_sales_person] updated: {updated}")
