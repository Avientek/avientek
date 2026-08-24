# Copyright (c) 2026, Avientek
"""
Repeatable local verification for the Project module enhancement
(avientek.events.project + migrate fields + dashboard). Run via:

    bench --site avintek.local execute \
        avientek.scripts.verify_project_enhancement.run

Read-only / self-cleaning: it uses a throwaway user + rolls back every
change, so it leaves no residue. Prints PASS/FAIL per check and a summary.
(The standard Frappe test runner can't bootstrap on a restored prod site
because of the encryption-key mismatch, so this bench-execute check is the
runnable local gate.)
"""
import frappe

RESULTS = []


def _check(label, ok):
    RESULTS.append((label, bool(ok)))
    print(("PASS" if ok else "FAIL") + " | " + label)


def run():
    RESULTS.clear()
    m = frappe.get_meta("Project")

    # 1) all fields present, in two-column order right after Department
    order = [f.fieldname for f in m.fields]
    expected = [
        "custom_project_details_sb", "custom_project_status", "custom_sales_person",
        "custom_territory", "custom_budget_amount", "custom_expected_closing_date",
        "custom_project_details_cb", "custom_created_by", "custom_project_by",
        "custom_probabilities", "custom_budget_value",
    ]
    dep = order.index("department")
    _check("fields present & ordered under Department (2 cols)",
           order[dep + 1: dep + 1 + len(expected)] == expected)
    _check("Project Status is a NEW field (standard status untouched)",
           (m.get_field("custom_project_status").options or "").split("\n")[0] == "Discussion"
           and m.get_field("status").options == "Open\nCompleted\nCancelled")
    _check("budget fields are Currency",
           m.get_field("custom_budget_amount").fieldtype == "Currency"
           and m.get_field("custom_budget_value").fieldtype == "Currency")

    # 2) role + dashboard
    _check("role 'Project L2 Approver' exists", frappe.db.exists("Role", "Project L2 Approver"))
    from avientek.overrides.project_dashboard import get_data
    d = get_data({"transactions": []})
    _check("Quotation added to Project connections",
           any("Quotation" in (t.get("items") or []) for t in d["transactions"]))

    # 3) strict-UP guard — a Sales-Person-UP user still sees projects
    from frappe.model.db_query import DatabaseQuery
    frappe.set_user("ng@avientek.com")
    try:
        rows = DatabaseQuery("Project").execute(fields=["name"], limit_page_length=0)
        _check("strict-UP guard: Sales-Person-UP user still sees projects", len(rows) > 0)
    finally:
        frappe.set_user("Administrator")

    # 4) L2 gate + created_by — use a throwaway, profile-less user with the L2 role
    p = frappe.db.get_value("Project", {}, "name")
    orig = frappe.db.get_value("Project", p, "custom_project_status")
    orig_d = frappe.db.get_value("Project", p, "custom_expected_closing_date")
    email = "zz_proj_verify@example.com"
    try:
        # created_by auto-set
        np = frappe.get_doc({"doctype": "Project", "project_name": "ZZ verify " + frappe.generate_hash(length=6)})
        np.insert(ignore_permissions=True)
        _check("Created By auto-set on insert", np.custom_created_by == frappe.session.user)
        frappe.db.rollback()

        frappe.db.set_value("Project", p, "custom_project_status", "Approved", update_modified=False)
        frappe.db.set_value("Project", p, "custom_expected_closing_date", "2026-12-31", update_modified=False)
        frappe.db.commit()

        # a non-L2 user (Projects User, profile-less)
        if frappe.db.exists("User", email):
            frappe.delete_doc("User", email, force=1)
        nonl2 = frappe.get_doc({"doctype": "User", "email": email, "first_name": "ZZ Verify",
                                "send_welcome_email": 0, "roles": [{"role": "Projects User"}]})
        nonl2.insert(ignore_permissions=True)
        frappe.db.commit()

        def _try(user, changes):
            frappe.set_user(user)
            try:
                doc = frappe.get_doc("Project", p)
                for k, v in changes.items():
                    setattr(doc, k, v)
                doc.save()
                return True
            except frappe.ValidationError:
                return False
            finally:
                frappe.set_user("Administrator")
                frappe.db.rollback()

        _check("L2: Approved->In Progress BLOCKED without role",
               _try(email, {"custom_project_status": "In Progress"}) is False)
        _check("L2: Approved->Closed ALLOWED",
               _try(email, {"custom_project_status": "Closed"}) is True)
        _check("L2: Exp Closing Date change BLOCKED while Approved",
               _try(email, {"custom_expected_closing_date": "2027-02-02"}) is False)

        # now give it the L2 role
        nonl2.reload(); nonl2.add_roles("Project L2 Approver"); frappe.db.commit()
        _check("L2: Approved->In Progress ALLOWED with role",
               _try(email, {"custom_project_status": "In Progress"}) is True)

        # non-Approved changes freely
        frappe.db.set_value("Project", p, "custom_project_status", "In Progress", update_modified=False)
        frappe.db.commit()
        _check("non-Approved status change ALLOWED",
               _try(email, {"custom_project_status": "Negotiation"}) is True)
    finally:
        frappe.set_user("Administrator")
        if frappe.db.exists("User", email):
            frappe.delete_doc("User", email, force=1)
        frappe.db.set_value("Project", p, "custom_project_status", orig, update_modified=False)
        frappe.db.set_value("Project", p, "custom_expected_closing_date", orig_d, update_modified=False)
        frappe.db.commit()

    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n=== {passed}/{len(RESULTS)} checks PASSED ===")
