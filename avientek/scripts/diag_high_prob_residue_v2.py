"""Deeper hunt for residue. Earlier cleanup got tabDocField but the
'Not found' popup still fires — something else points at the missing
child doctype."""
import frappe


def run():
    print("=" * 70)
    print(f"DEEP RESIDUE HUNT — site: {frappe.local.site}")
    print("=" * 70)

    # 1. tabCustom Field (separate from tabDocField)
    rows = frappe.db.sql(
        """SELECT name, dt, fieldname, fieldtype, options
           FROM `tabCustom Field`
           WHERE dt = 'Avientek Settings'
              OR fieldname LIKE 'quote_high_prob%'
              OR options = 'Avientek Quotation Restricted Role'
              OR options = 'Quotation Action Request'""",
        as_dict=True,
    )
    print(f"\n[1] tabCustom Field hits: {len(rows)}")
    for r in rows:
        print(f"  - name={r.name}  dt={r.dt}  fieldname={r.fieldname}  "
              f"fieldtype={r.fieldtype}  options={r.options!r}")

    # 2. Property Setter
    rows = frappe.db.sql(
        """SELECT name, doc_type, field_name, property, value
           FROM `tabProperty Setter`
           WHERE doc_type = 'Avientek Settings'
              OR field_name LIKE 'quote_high_prob%'
              OR value LIKE '%Avientek Quotation Restricted Role%'
              OR value LIKE '%Quotation Action Request%'""",
        as_dict=True,
    )
    print(f"\n[2] tabProperty Setter hits: {len(rows)}")
    for r in rows:
        print(f"  - name={r.name}  doc_type={r.doc_type}  "
              f"field={r.field_name}  property={r.property}  value={r.value!r}")

    # 3. tabSingles for Avientek Settings (the actual saved values)
    rows = frappe.db.sql(
        """SELECT field, value FROM `tabSingles`
           WHERE doctype='Avientek Settings'
             AND (field LIKE 'quote_high_prob%' OR value LIKE '%Restricted Role%')""",
        as_dict=True,
    )
    print(f"\n[3] tabSingles hits: {len(rows)}")
    for r in rows:
        print(f"  - field={r.field}  value={r.value!r}")

    # 4. Workflow records that still point at Quotation Action Request
    rows = frappe.db.sql(
        """SELECT name FROM `tabWorkflow`
           WHERE document_type='Quotation Action Request'""",
        as_dict=True,
    )
    print(f"\n[4] Workflow rows for Quotation Action Request: {len(rows)}")
    for r in rows:
        print(f"  - {r.name}")

    # 5. Search ALL DocFields for any remaining references
    rows = frappe.db.sql(
        """SELECT parent, fieldname, fieldtype, options
           FROM `tabDocField`
           WHERE options IN ('Avientek Quotation Restricted Role',
                              'Quotation Action Request')
              OR fieldname LIKE 'quote_high_prob%'""",
        as_dict=True,
    )
    print(f"\n[5] tabDocField hits: {len(rows)}")
    for r in rows:
        print(f"  - parent={r.parent}  fieldname={r.fieldname}  "
              f"fieldtype={r.fieldtype}  options={r.options!r}")

    # 6. Patch Log entries from the seeder (so it doesn't try to re-seed)
    rows = frappe.db.sql(
        """SELECT patch FROM `tabPatch Log`
           WHERE patch LIKE '%quotation_action_request%'
              OR patch LIKE '%high_prob%'""",
        as_dict=True,
    )
    print(f"\n[6] Patch Log hits: {len(rows)}")
    for r in rows:
        print(f"  - {r.patch}")

    # 7. Customize Form fields exported on disk — JSON files
    import os, json
    custom_dir = frappe.get_app_path("avientek", "..", "avientek", "avientek", "custom")
    custom_dir2 = frappe.get_app_path("avientek", "avientek", "custom")
    print(f"\n[7] Customize Form file scan")
    for d in (custom_dir, custom_dir2):
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".json"):
                continue
            try:
                content = open(os.path.join(d, fn)).read()
                if "quote_high_prob" in content or "Avientek Quotation Restricted Role" in content:
                    print(f"  - HIT in {fn}")
            except Exception:
                pass
