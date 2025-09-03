import frappe

# -------------------------------
# Configuration
# -------------------------------

PQ_CHILD_TABLE = "Sales Person Project"   # exact child DocType name
PQ_CHILD_LINK_FIELD = "sales_person"      # field in child table linking to Sales Person
QUOTATION_PQ_LINKFIELD = "custom_quote_project"


# -------------------------------
# Helper functions
# -------------------------------

def _user_allowed_sales_persons(user: str) -> list[str]:
    """Return Sales Person names that the user has access to."""
    return frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Sales Person"},
        pluck="for_value",
    )


# -------------------------------
# Project Quotation
# -------------------------------

def project_quotation_pqc(user: str) -> str:
    """Permission query for Project Quotation (for reports / list views)."""
    if "System Manager" in frappe.get_roles(user):
        return ""

    sps = _user_allowed_sales_persons(user)
    if not sps:
        return "1=0"

    in_list = ", ".join(f"'{v}'" for v in sps)
    return f"""
        exists (
            select 1
            from `tab{PQ_CHILD_TABLE}` sp
            where sp.parent = `tabProject Quotation`.name
              and sp.{PQ_CHILD_LINK_FIELD} in ({in_list})
        )
    """


def project_quotation_has_perm(doc, user: str) -> bool:
    """Hard guard when opening a Project Quotation directly."""
    if "System Manager" in frappe.get_roles(user):
        return True

    sps = set(_user_allowed_sales_persons(user))
    if not sps:
        return False

    rows = frappe.get_all(PQ_CHILD_TABLE, filters={"parent": doc.name}, pluck=PQ_CHILD_LINK_FIELD)
    return bool(set(rows) & sps)




@frappe.whitelist()
def get_project_quotation_for_user(doctype, txt, searchfield, start, page_len, filters=None):
    user = frappe.session.user

    # System Manager sees everything
    if "System Manager" in frappe.get_roles(user):
        projects = frappe.get_all(
            "Project Quotation",
            filters={searchfield: ["like", f"%{txt}%"]} if txt else {},
            fields=["name", "project_name"],
            limit_start=start,
            limit_page_length=page_len,
        )
        return [[p.name, p.project_name or ""] for p in projects]

    # Get allowed Sales Persons from User Permissions
    sps = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Sales Person"},
        pluck="for_value",
    )

    if not sps:
        return []

    # prepare placeholders
    placeholders = ", ".join(["%s"] * len(sps))
    params = sps

    # apply LIKE filter if search text given
    like_clause = f"AND pq.{searchfield} LIKE %s" if txt else ""
    if txt:
        params.append(f"%{txt}%")

    query = f"""
        SELECT DISTINCT pq.name, pq.project_name
        FROM `tabProject Quotation` pq
        INNER JOIN `tabSales Person Project` sp
            ON sp.parent = pq.name
        WHERE sp.sales_person IN ({placeholders})
        {like_clause}
        ORDER BY pq.name
        LIMIT {start}, {page_len}
    """


    projects = frappe.db.sql(query, params, as_dict=1)

    frappe.errprint("Projects fetched:")
    for p in projects:
        linked_sps = frappe.get_all(
            "Sales Person Project",
            filters={"parent": p["name"]},
            pluck="sales_person"
        )
        frappe.errprint(f"- {p['name']} ({p.get('project_name')}) → {linked_sps}")

    return [[p["name"], p.get("project_name") or ""] for p in projects]


# -------------------------------
# Quotation
# -------------------------------

def quotation_pqc(user: str) -> str:
    """Permission query for Quotation (filters based on linked PQ)."""
    if "System Manager" in frappe.get_roles(user):
        return ""

    sps = _user_allowed_sales_persons(user)
    if not sps:
        return "1=0"

    in_list = ", ".join(f"'{v}'" for v in sps)
    return f"""
        exists (
            select 1
            from `tabProject Quotation` pq
            join `tab{PQ_CHILD_TABLE}` sp on sp.parent = pq.name
            where pq.name = `tabQuotation`.{QUOTATION_PQ_LINKFIELD}
              and sp.{PQ_CHILD_LINK_FIELD} in ({in_list})
        )
    """


def quotation_has_perm(doc, user: str) -> bool:
    """Hard guard when opening a Quotation directly."""
    if "System Manager" in frappe.get_roles(user):
        return True

    sps = set(_user_allowed_sales_persons(user))
    if not sps:
        return False

    pq_name = getattr(doc, QUOTATION_PQ_LINKFIELD, None)
    if not pq_name:
        return False

    rows = frappe.get_all(PQ_CHILD_TABLE, filters={"parent": pq_name}, pluck=PQ_CHILD_LINK_FIELD)
    return bool(set(rows) & sps)
