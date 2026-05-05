"""Inspect Quotation workflow states + active workflow on this site.
Drives card filter design when production cards aren't replicated here.
"""
import frappe


def run():
    print("Active Workflows on Quotation:")
    wfs = frappe.db.sql(
        """SELECT name, document_type, is_active, workflow_state_field
           FROM `tabWorkflow`
           WHERE document_type='Quotation'
           ORDER BY is_active DESC, name""", as_dict=True,
    )
    for w in wfs:
        print(f"  {w['name']:35s} active={w['is_active']} "
              f"state_field={w['workflow_state_field']}")

    print("\nDistinct workflow_state values currently on Quotations:")
    rows = frappe.db.sql(
        """SELECT workflow_state, COUNT(*) AS n FROM `tabQuotation`
           WHERE IFNULL(workflow_state,'') <> ''
           GROUP BY workflow_state ORDER BY n DESC""", as_dict=True,
    )
    for r in rows:
        print(f"  {r['workflow_state']:35s} {r['n']}")

    print("\nDistinct status values:")
    rows = frappe.db.sql(
        """SELECT status, COUNT(*) AS n FROM `tabQuotation`
           GROUP BY status ORDER BY n DESC""", as_dict=True,
    )
    for r in rows:
        print(f"  {r['status']:35s} {r['n']}")
