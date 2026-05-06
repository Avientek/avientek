import frappe


def run():
    rows = frappe.db.sql(
        """SELECT tr_type, COUNT(*) AS n FROM `tabPayment Request Form`
           WHERE IFNULL(tr_type,'') <> ''
           GROUP BY tr_type ORDER BY n DESC""",
        as_dict=True,
    )
    print("Distinct tr_type values:")
    for r in rows:
        print(f"  {r['tr_type']!r}: {r['n']}")
    # Also dump the field options from the doctype
    meta = frappe.get_meta("Payment Request Form")
    fmap = {f.fieldname: f for f in meta.fields}
    tr = fmap.get("tr_type")
    if tr:
        print(f"\ntr_type fieldtype = {tr.fieldtype}, options =\n{tr.options}")
