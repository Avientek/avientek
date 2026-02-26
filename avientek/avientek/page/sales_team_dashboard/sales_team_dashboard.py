import frappe
from frappe.utils import flt

from avientek.events.sales_person_permission import _user_allowed_sales_persons


OPEN_STATUSES = ("To Deliver and Bill", "To Deliver", "To Bill")


def _get_sales_person_condition(user):
    """Build SQL condition for Sales Person-based access control."""
    if user == "Administrator" or "System Manager" in frappe.get_roles(user):
        return "", []

    sps = _user_allowed_sales_persons(user)
    if not sps:
        return "1=0", []

    placeholders = ", ".join(["%s"] * len(sps))
    condition = (
        f"EXISTS ("
        f"SELECT 1 FROM `tabSales Team` st "
        f"WHERE st.parent = so.name "
        f"AND st.parenttype = 'Sales Order' "
        f"AND st.sales_person IN ({placeholders})"
        f")"
    )
    return condition, list(sps)


def _build_where(company, from_date, to_date, user, customer=None, brand=None, sales_person=None):
    """Build WHERE clause and params list."""
    conditions = ["so.docstatus = 1", "so.status NOT IN ('Cancelled', 'Closed')"]
    params = []

    if company:
        conditions.append("so.company = %s")
        params.append(company)
    if from_date:
        conditions.append("so.transaction_date >= %s")
        params.append(from_date)
    if to_date:
        conditions.append("so.transaction_date <= %s")
        params.append(to_date)
    if customer:
        conditions.append("so.customer = %s")
        params.append(customer)
    if brand:
        conditions.append(
            "EXISTS ("
            "SELECT 1 FROM `tabSales Order Item` _soi "
            "WHERE _soi.parent = so.name AND _soi.brand = %s"
            ")"
        )
        params.append(brand)
    if sales_person:
        conditions.append(
            "EXISTS ("
            "SELECT 1 FROM `tabSales Team` _sp "
            "WHERE _sp.parent = so.name "
            "AND _sp.parenttype = 'Sales Order' "
            "AND _sp.sales_person = %s"
            ")"
        )
        params.append(sales_person)

    sp_cond, sp_params = _get_sales_person_condition(user)
    if sp_cond:
        conditions.append(sp_cond)
        params.extend(sp_params)

    return " AND ".join(conditions), params


@frappe.whitelist()
def get_dashboard_data(company=None, from_date=None, to_date=None, customer=None, brand=None, sales_person=None):
    user = frappe.session.user
    where_clause, params = _build_where(company, from_date, to_date, user, customer, brand, sales_person)
    open_placeholders = ", ".join(["%s"] * len(OPEN_STATUSES))

    # --- Query 1: Summary totals ---
    summary_sql = f"""
        SELECT
            COUNT(*) AS total_count,
            IFNULL(SUM(so.base_grand_total), 0) AS total_value,
            SUM(CASE WHEN so.status IN ({open_placeholders}) THEN 1 ELSE 0 END) AS open_count,
            IFNULL(SUM(CASE WHEN so.status IN ({open_placeholders})
                        THEN so.base_grand_total ELSE 0 END), 0) AS open_value
        FROM `tabSales Order` so
        WHERE {where_clause}
    """
    summary_params = list(OPEN_STATUSES) + list(OPEN_STATUSES) + params
    summary = frappe.db.sql(summary_sql, summary_params, as_dict=True)[0]

    # --- Query 2: Invoices linked to open SOs ---
    si_sql = f"""
        SELECT DISTINCT si.name, si.base_grand_total
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus = 1
        INNER JOIN `tabSales Order` so ON so.name = sii.sales_order
        WHERE so.status IN ({open_placeholders})
          AND {where_clause}
    """
    si_rows = frappe.db.sql(si_sql, list(OPEN_STATUSES) + params, as_dict=True)

    # --- Query 3: Customer-wise breakdown (open SOs) ---
    cust_sql = f"""
        SELECT so.customer, so.customer_name,
               COUNT(*) AS count,
               IFNULL(SUM(so.base_grand_total), 0) AS value
        FROM `tabSales Order` so
        WHERE so.status IN ({open_placeholders}) AND {where_clause}
        GROUP BY so.customer
        ORDER BY value DESC
    """
    customer_data = frappe.db.sql(cust_sql, list(OPEN_STATUSES) + params, as_dict=True)

    # --- Query 4: Brand-wise breakdown (open SOs) ---
    brand_sql = f"""
        SELECT soi.brand,
               COUNT(DISTINCT so.name) AS so_count,
               IFNULL(SUM(soi.base_amount), 0) AS value
        FROM `tabSales Order Item` soi
        INNER JOIN `tabSales Order` so ON so.name = soi.parent
        WHERE so.status IN ({open_placeholders}) AND {where_clause}
          AND IFNULL(soi.brand, '') != ''
        GROUP BY soi.brand
        ORDER BY value DESC
    """
    brand_data = frappe.db.sql(brand_sql, list(OPEN_STATUSES) + params, as_dict=True)

    currency = ""
    if company:
        currency = frappe.get_cached_value("Company", company, "default_currency") or ""
    if not currency:
        currency = frappe.db.get_default("currency") or ""

    return {
        "summary": {
            "total_count": summary.total_count or 0,
            "total_value": flt(summary.total_value),
            "open_count": summary.open_count or 0,
            "open_value": flt(summary.open_value),
            "invoice_count": len(si_rows),
            "invoice_value": flt(sum(r.base_grand_total or 0 for r in si_rows)),
        },
        "customer_data": customer_data,
        "brand_data": brand_data,
        "currency": currency,
    }


@frappe.whitelist()
def get_customer_orders(customer, company=None, from_date=None, to_date=None,
                        brand=None, sales_person=None):
    """Return open Sales Orders and their linked invoices for a customer."""
    user = frappe.session.user
    where_clause, params = _build_where(
        company, from_date, to_date, user,
        customer=customer, brand=brand, sales_person=sales_person,
    )
    open_placeholders = ", ".join(["%s"] * len(OPEN_STATUSES))

    # Open Sales Orders
    so_sql = f"""
        SELECT so.name, so.transaction_date, so.status,
               so.base_grand_total, so.per_delivered, so.per_billed
        FROM `tabSales Order` so
        WHERE so.status IN ({open_placeholders}) AND {where_clause}
        ORDER BY so.transaction_date DESC
    """
    orders = frappe.db.sql(so_sql, list(OPEN_STATUSES) + params, as_dict=True)

    # Invoices linked to those open SOs
    si_sql = f"""
        SELECT DISTINCT
            si.name, si.posting_date, si.base_grand_total,
            si.outstanding_amount, si.status
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus = 1
        INNER JOIN `tabSales Order` so ON so.name = sii.sales_order
        WHERE so.status IN ({open_placeholders})
          AND {where_clause}
        ORDER BY si.posting_date DESC
    """
    invoices = frappe.db.sql(si_sql, list(OPEN_STATUSES) + params, as_dict=True)

    currency = ""
    if company:
        currency = frappe.get_cached_value("Company", company, "default_currency") or ""
    if not currency:
        currency = frappe.db.get_default("currency") or ""

    return {"orders": orders, "invoices": invoices, "currency": currency}


@frappe.whitelist()
def get_brand_orders(brand, company=None, from_date=None, to_date=None,
                     customer=None, sales_person=None):
    """Return open Sales Orders and their linked invoices for a brand (brand-specific amounts)."""
    user = frappe.session.user
    # Don't pass brand to _build_where — we filter by brand directly in queries
    where_clause, params = _build_where(
        company, from_date, to_date, user,
        customer=customer, sales_person=sales_person,
    )
    open_placeholders = ", ".join(["%s"] * len(OPEN_STATUSES))

    # Open Sales Orders containing this brand — brand-specific line item totals
    so_sql = f"""
        SELECT so.name, so.customer_name, so.transaction_date, so.status,
               IFNULL(SUM(soi.base_amount), 0) AS brand_amount,
               so.per_delivered, so.per_billed
        FROM `tabSales Order Item` soi
        INNER JOIN `tabSales Order` so ON so.name = soi.parent
        WHERE soi.brand = %s
          AND so.status IN ({open_placeholders})
          AND {where_clause}
        GROUP BY so.name
        ORDER BY so.transaction_date DESC
    """
    orders = frappe.db.sql(so_sql, [brand] + list(OPEN_STATUSES) + params, as_dict=True)

    # Invoices linked to those open SOs — brand-specific line item totals
    si_sql = f"""
        SELECT si.name, si.posting_date, si.status,
               IFNULL(SUM(sii.base_amount), 0) AS brand_amount
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus = 1
        INNER JOIN `tabSales Order` so ON so.name = sii.sales_order
        WHERE sii.brand = %s
          AND so.status IN ({open_placeholders})
          AND {where_clause}
        GROUP BY si.name
        ORDER BY si.posting_date DESC
    """
    invoices = frappe.db.sql(si_sql, [brand] + list(OPEN_STATUSES) + params, as_dict=True)

    currency = ""
    if company:
        currency = frappe.get_cached_value("Company", company, "default_currency") or ""
    if not currency:
        currency = frappe.db.get_default("currency") or ""

    return {"orders": orders, "invoices": invoices, "currency": currency}
