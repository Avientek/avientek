import frappe


# ── Server Script: "Get Filtered Customers" (API) ──
@frappe.whitelist()
def get_filtered_customers(company=None):
    """Return customers that belong to or are allowed to transact with the given company."""
    if not company:
        company = frappe.form_dict.get("company")

    customers = []

    if company:
        customers = frappe.db.get_all(
            "Customer",
            filters={"company": company, "disabled": 0},
            pluck="name",
        )
        # Also include customers with no company set (shared/inter-company)
        shared = frappe.db.get_all(
            "Customer",
            filters={"company": ["in", ["", None]], "disabled": 0},
            pluck="name",
        )
        customers = customers + shared
        allowed = frappe.db.get_all(
            "Allowed To Transact With",
            filters={
                "company": company,
                "parentfield": "companies",
                "parenttype": "Customer",
            },
            pluck="parent",
        )
        if allowed:
            customers = customers + allowed

    return frappe.utils.unique(customers)


# ── Server Script: "get_filtered_supplier" (API) ──
@frappe.whitelist()
def get_filtered_supplier(company=None):
    """Return suppliers that belong to or are allowed to transact with the given company."""
    if not company:
        company = frappe.form_dict.get("company")

    suppliers = []

    if company:
        suppliers = frappe.db.get_all(
            "Supplier",
            filters={"company": company, "disabled": 0},
            pluck="name",
        )
        allowed = frappe.db.get_all(
            "Allowed To Transact With",
            filters={
                "company": company,
                "parentfield": "companies",
                "parenttype": "Supplier",
            },
            pluck="parent",
        )
        if allowed:
            suppliers = suppliers + allowed

    return frappe.utils.unique(suppliers)
