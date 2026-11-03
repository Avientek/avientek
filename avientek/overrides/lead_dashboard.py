# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
"""Show the converted Customer in the Lead form's Connections panel
(Sridhar 2026-09-09).

When a Lead is converted, ERPNext stamps the Lead on the new Customer in the
standard `Customer.lead_name` field — but the stock Lead dashboard only lists
Opportunity / Quotation / Prospect, so there is no way to get from a Lead to
the Customer it became without searching for it.

`lead_name` is not the dashboard's default fieldname (`lead`), so Customer has
to go in `non_standard_fieldnames`; it is a plain Link → Lead, so it needs no
`dynamic_links` entry the way Quotation/Opportunity's `party_name` does.

This is also the link the Project brand fetch walks
(Project.customer → Customer.lead_name → Lead.custom_focused_brands, see
avientek.events.project.fetch_brands_from_lead), so having it visible on the
Lead makes that chain checkable from the form.
"""
from frappe import _


def get_data(data):
    fieldnames = data.setdefault("non_standard_fieldnames", {})
    fieldnames["Customer"] = "lead_name"
    # Manu 2026-10-31: projects raised for this Lead (Project.custom_lead).
    fieldnames["Project"] = "custom_lead"

    data.setdefault("transactions", [])
    for doctype in ("Customer", "Project"):
        _add_item(data["transactions"], doctype)
    return data


def _add_item(transactions, doctype):
    # Sit alongside Opportunity / Quotation / Prospect in ERPNext's own group
    # rather than adding a second header. Guarded so a reload cannot list
    # the doctype twice.
    for group in transactions:
        if doctype in group.setdefault("items", []):
            return
    for group in transactions:
        if not group.get("label"):
            group["items"].append(doctype)
            return
    transactions.append({"label": _("Converted"), "items": [doctype]})
