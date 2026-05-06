"""Detect leftover high-probability artefacts from feature/quotation-high-prob
on a site that's currently on master. Sridhar 2026-05-06."""
import frappe


def run():
    print("=" * 70)
    print(f"HIGH-PROB RESIDUE CHECK — site: {frappe.local.site}")
    print("=" * 70)

    findings = []

    # 1. Avientek Settings DocType: are the high-prob fields still in the DB?
    rows = frappe.db.sql(
        """SELECT fieldname, fieldtype, options
           FROM `tabDocField`
           WHERE parent = 'Avientek Settings'
             AND fieldname LIKE 'quote_high_prob%'
           ORDER BY idx""", as_dict=True,
    )
    if rows:
        findings.append("Avientek Settings has the high-prob fields in DB:")
        for r in rows:
            findings.append(f"   - {r.fieldname:42s} {r.fieldtype:18s} {r.options or ''}")
    else:
        findings.append("Avientek Settings has NO high-prob fields in DB (clean).")

    # 2. Are the new doctypes in DB?
    for dt in ("Quotation Action Request", "Avientek Quotation Restricted Role"):
        if frappe.db.exists("DocType", dt):
            findings.append(f"DocType '{dt}' EXISTS in DB.")
        else:
            findings.append(f"DocType '{dt}' is gone from DB.")

    # 3. Workflow exists?
    if frappe.db.exists("Workflow", "Quotation Action Request Approval"):
        findings.append("Workflow 'Quotation Action Request Approval' EXISTS in DB.")
    else:
        findings.append("Workflow 'Quotation Action Request Approval' is gone.")

    # 4. Workflow State / Action Master records seeded by us
    for ws in ("L1 Approved", "L2 Approved", "Executed"):
        if frappe.db.exists("Workflow State", ws):
            findings.append(f"Workflow State '{ws}' EXISTS.")
    for wa in ("Approve L1", "Approve L2"):
        if frappe.db.exists("Workflow Action Master", wa):
            findings.append(f"Workflow Action Master '{wa}' EXISTS.")

    # 5. Any QAR records?
    if frappe.db.table_exists("Quotation Action Request"):
        n = frappe.db.sql("SELECT COUNT(*) FROM `tabQuotation Action Request`")[0][0]
        findings.append(f"Quotation Action Request rows in DB: {n}")

    # 6. Git branch the bench is currently on
    import subprocess, os
    app_path = frappe.get_app_path("avientek", "..")
    try:
        out = subprocess.check_output(
            ["git", "-C", app_path, "branch", "--show-current"],
        ).decode().strip()
        findings.append(f"Avientek app current git branch: {out!r}")
        last = subprocess.check_output(
            ["git", "-C", app_path, "log", "-1", "--oneline"],
        ).decode().strip()
        findings.append(f"Avientek app HEAD: {last}")
    except Exception as e:
        findings.append(f"git inspection failed: {e}")

    print()
    for line in findings:
        print(f"  {line}")
    print()

    # Summarise the cleanup needed.
    needs_cleanup = (
        rows or
        any(frappe.db.exists("DocType", d) for d in
            ("Quotation Action Request", "Avientek Quotation Restricted Role"))
        or frappe.db.exists("Workflow", "Quotation Action Request Approval")
    )
    if needs_cleanup:
        print("→ CLEANUP NEEDED. The site has high-prob feature artefacts.")
        print("  Run: bench --site <site> execute "
              "avientek.scripts.cleanup_high_prob_residue.run")
    else:
        print("→ Site is clean. No leftover high-prob artefacts.")
    return findings
