from frappe.utils import get_url
import frappe
from frappe.email.doctype.email_template.email_template import get_email_template

@frappe.whitelist()
def get_sales_orders(company_name):
    sql_data = []
    query = f'''
        SELECT 
            c.name AS customer_name, c.email_id AS customer_mail, so.name AS sales_order_name, so.po_no, so.status,
            soi.item_code, soi.part_number, (soi.qty - soi.delivered_qty) AS qty, soi.avientek_eta as eta
        FROM 
            `tabCustomer` c
        LEFT JOIN          
            `tabSales Order` so ON c.name = so.customer
        LEFT JOIN
            `tabSales Order Item` soi ON so.name = soi.parent
        WHERE 
            c.disabled = 0 AND so.docstatus = 1 AND so.per_delivered < 100 AND soi.delivered_qty<soi.qty AND so.company = "{company_name}"
    '''

    sql_data = frappe.db.sql(query, as_dict=True)
    grouped_data = {}
    for row in sql_data:
        customer_mail = row.customer_mail
        if customer_mail not in grouped_data:
            grouped_data[customer_mail] = []
        grouped_data[customer_mail].append(row)
    return grouped_data


@frappe.whitelist()
def send_email_to_customer(customer_email, sales_orders):
    sales_orders = frappe.parse_json(sales_orders)
    subject = 'Latest ETA on open orders'
    message = '<b>PFB the latest ETA for your open orders :</b><br><br>'

    if not isinstance(sales_orders, list):
        frappe.throw("Invalid data format for sales_orders")

    table = "<table border='1' style='border-collapse: collapse; width: 100%;'>" \
            "<tr><th style=' width: 20%;' >Sales Order</th><th style=' width: 20%; '>PO Number</th>" \
            "<th style=' width: 15%;'>Item Code</th><th style=' width: 20%;'>Part Number</th><th style=' width: 15%;'>Quantity</th><th style=' width: 10%;'>ETA</th></tr>"

    for order in sales_orders:
        if not isinstance(order, dict):
            frappe.throw("Invalid data format for sales_orders")

        table += format_order_details(order)

    table += "</table><br>"

    frappe.sendmail(
        recipients = customer_email,
        subject = subject,
        message = message + table,
    )
    return 'success'

def format_order_details(order):

    table = ""
    table += f"<tr><td><center>{order.get('sales_order_name')}</center></td>" \
        f"<td><center>{order.get('po_no')}</center></td>"
    
    table += f"<td><center>{order.get('item_code')}</center></td>" \
        f"<td><center>{order.get('part_number')}</center></td>" \
        f"<td><center>{order.get('qty')}</center></td>" \
        f"<td><center>{order.get('eta')}</center></td></tr>"

    return table





