import frappe


def execute():
    """Remove stale column break fields from Quotation Item."""
    fields_to_delete = [
        "Quotation Item-column_break_32",
        "Quotation Item-custom_column_break_calc_4",
        "Quotation Item-column_break_38",
    ]
    for name in fields_to_delete:
        if frappe.db.exists("Custom Field", name):
            frappe.delete_doc("Custom Field", name, force=True)
            frappe.db.commit()
