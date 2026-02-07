# Copyright (c) 2025, Avientek and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ProjectQuotation(Document):
	pass



# @frappe.whitelist()
# def get_allowed_projects(doctype, txt, searchfield, start, page_len, filters):
#     """
#     Returns Project Quotations where the Sales Person in the current Quotation
#     is included in the MultiSelectList field 'salesperson' of Project Quotation.
#     """
#     # Get Sales Person from the current Quotation filters
#     salesperson = filters.get("sales_person")  # 'sales_person' is fieldname in Quotation
#     if not salesperson:
#         # fallback to logged-in user's name if needed
#         salesperson = frappe.session.user

#     # Query Project Quotations containing this salesperson
#     projects = frappe.db.sql("""
#         SELECT name, project_name
#         FROM `tabProject Quotation`
#         WHERE FIND_IN_SET(%(salesperson)s, salesperson)
#           AND (name LIKE %(txt)s OR project_name LIKE %(txt)s)
#         ORDER BY name
#         LIMIT %(start)s, %(page_len)s
#     """, {
#         "salesperson": salesperson,
#         "txt": f"%{txt}%",
#         "start": start,
#         "page_len": page_len
#     }, as_dict=True)

#     return [{"value": p["name"], "description": p["project_name"]} for p in projects]
