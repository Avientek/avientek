# Copyright (c) 2026, Avientek
"""
Repeatable local verification for the Project module enhancement
(avientek.events.project + migrate fields + dashboard). Run via:

    bench --site avintek.local execute \
        avientek.scripts.verify_project_enhancement.run

Self-cleaning: uses an existing non-privileged user (ng@avientek.com) and a
`frappe.get_roles` monkeypatch to simulate the L2 role, and rolls back every
change — so it creates NO users and leaves no residue. (Creating/saving a User
triggers share_with_self -> tabdocshare, which deadlocks against a running
`bench start`; and the standard Frappe test runner can't bootstrap on a
restored prod site because of the encryption-key mismatch — so this
bench-execute check is the runnable local gate.)

Prints PASS/FAIL per check and a summary.
"""
import frappe

RESULTS = []
NON_ADMIN = "ng@avientek.com"  # Projects User, not System Manager, not L2


def _check(label, ok):
    RESULTS.append((label, bool(ok)))
    print(("PASS" if ok else "FAIL") + " | " + label)


def _save_as(user, changes, extra_roles=None):
    """Try to save PROJ-0110 changes as `user`; return True if saved, False if
    the L2 validation blocked it. Always rolls back. `extra_roles` (a set)
    is injected into frappe.get_roles to simulate held roles without touching
    the User doc."""
    orig_get_roles = frappe.get_roles
    if extra_roles:
        def _patched(u=None, *a, **k):
            return list(orig_get_roles(u, *a, **k)) + list(extra_roles)
        frappe.get_roles = _patched
    frappe.set_user(user)
    try:
        doc = frappe.get_doc("Project", "PROJ-0110")
        for k, v in changes.items():
            setattr(doc, k, v)
        doc.save()
        return True
    except frappe.ValidationError:
        return False
    finally:
        frappe.get_roles = orig_get_roles
        frappe.set_user("Administrator")
        frappe.db.rollback()


def run():
    RESULTS.clear()
    m = frappe.get_meta("Project")

    # 1) fields present + two-column order right after Department
    order = [f.fieldname for f in m.fields]
    expected = [
        "custom_project_details_sb", "custom_project_status", "custom_sales_person",
        "custom_parent_sales_person", "custom_territory", "custom_budget_amount",
        "custom_expected_closing_date",
        "custom_project_details_cb", "custom_created_by", "custom_project_by",
        "custom_budget_value",
    ]
    dep = order.index("department")
    _check("fields present & ordered under Department (2 cols)",
           order[dep + 1: dep + 1 + len(expected)] == expected)
    _check("Probabilities removed; Parent Sales Person present (auto)",
           not m.get_field("custom_probabilities")
           and bool(m.get_field("custom_parent_sales_person")))
    _check("Assigned to Sales Person label + Discussion removed from status",
           m.get_field("custom_sales_person").label == "Assigned to Sales Person"
           and "Discussion" not in (m.get_field("custom_project_status").options or ""))
    _check("Project Status is a NEW field (standard status untouched)",
           (m.get_field("custom_project_status").options or "").split("\n")[0] == "Open"
           and m.get_field("status").options == "Open\nCompleted\nCancelled")
    _check("budget fields are Currency",
           m.get_field("custom_budget_amount").fieldtype == "Currency"
           and m.get_field("custom_budget_value").fieldtype == "Currency")

    # 2) role + dashboard + strict-UP guard
    _check("role 'Project L2 Approver' exists", frappe.db.exists("Role", "Project L2 Approver"))
    from avientek.overrides.project_dashboard import get_data
    d = get_data({"transactions": []})
    _check("Quotation added to Project connections",
           any("Quotation" in (t.get("items") or []) for t in d["transactions"]))
    from frappe.model.db_query import DatabaseQuery
    frappe.set_user(NON_ADMIN)
    try:
        rows = DatabaseQuery("Project").execute(fields=["name"], limit_page_length=0)
    finally:
        frappe.set_user("Administrator")
    _check("strict-UP guard: Sales-Person-UP user still sees projects", len(rows) > 0)

    # 3) Created By auto-set on insert (rolled back)
    np = frappe.get_doc({"doctype": "Project", "project_name": "ZZ verify " + frappe.generate_hash(length=6)})
    np.insert(ignore_permissions=True)
    _check("Created By auto-set on insert", np.custom_created_by == frappe.session.user)
    frappe.db.rollback()

    # 4) L2 gate — set PROJ-0110 Approved, then exercise the paths as ng
    p = "PROJ-0110"
    orig_status = frappe.db.get_value("Project", p, "custom_project_status")
    orig_date = frappe.db.get_value("Project", p, "custom_expected_closing_date")
    try:
        frappe.db.set_value("Project", p, "custom_project_status", "Approved", update_modified=False)
        frappe.db.set_value("Project", p, "custom_expected_closing_date", "2026-12-31", update_modified=False)
        frappe.db.commit()

        _check("L2: Approved->In Progress BLOCKED without role",
               _save_as(NON_ADMIN, {"custom_project_status": "In Progress"}) is False)
        _check("L2: Approved->Closed ALLOWED",
               _save_as(NON_ADMIN, {"custom_project_status": "Closed"}) is True)
        _check("L2: Exp Closing Date change BLOCKED while Approved",
               _save_as(NON_ADMIN, {"custom_expected_closing_date": "2027-02-02"}) is False)
        _check("L2: Approved->In Progress ALLOWED with role",
               _save_as(NON_ADMIN, {"custom_project_status": "In Progress"},
                        extra_roles={"Project L2 Approver"}) is True)

        frappe.db.set_value("Project", p, "custom_project_status", "In Progress", update_modified=False)
        frappe.db.commit()
        _check("non-Approved status change ALLOWED",
               _save_as(NON_ADMIN, {"custom_project_status": "Negotiation"}) is True)
    finally:
        frappe.db.set_value("Project", p, "custom_project_status", orig_status, update_modified=False)
        frappe.db.set_value("Project", p, "custom_expected_closing_date", orig_date, update_modified=False)
        frappe.db.commit()

    passed = sum(1 for _, ok in RESULTS if ok)
    print("\n=== {}/{} checks PASSED ===".format(passed, len(RESULTS)))
