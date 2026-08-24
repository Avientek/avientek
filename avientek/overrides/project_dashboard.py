# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
"""Add Quotation to the Project form's Connections panel (Project enhancement
point 9). Quotation.project links to Project via the standard `project`
fieldname, so no non_standard_fieldnames entry is needed."""
from frappe import _


def get_data(data):
    data.setdefault("transactions", [])
    # Add Quotation to the existing "Sales" group if there is one, so we don't
    # create a second "Sales" header; otherwise add a new group.
    for group in data["transactions"]:
        if group.get("label") in ("Sales", _("Sales")):
            items = group.setdefault("items", [])
            if "Quotation" not in items:
                items.insert(0, "Quotation")
            break
    else:
        data["transactions"].append({"label": _("Sales"), "items": ["Quotation"]})
    return data
