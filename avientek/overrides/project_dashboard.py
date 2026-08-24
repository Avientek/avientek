# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
"""Add Quotation to the Project form's Connections panel (Project enhancement
point 9). Quotation.project links to Project via the standard `project`
fieldname, so no non_standard_fieldnames entry is needed."""
from frappe import _


def get_data(data):
    data.setdefault("transactions", [])
    data["transactions"].append({
        "label": _("Sales"),
        "items": ["Quotation"],
    })
    return data
