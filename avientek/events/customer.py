import frappe
from frappe.utils import flt


# ── Credit Limit roll-up ──
# DocType Event: Customer, Before Save
def sync_credit_limit_totals(doc, method=None):
    """Set Customer Credit Limit row's `credit_limit` = custom_insured_limit
    + custom_internal_limit on every save.

    Why server-side too (when JS already does it on field-change): covers
    data import, REST API writes, server scripts, and any other path that
    bypasses the form. ERPNext's check_credit_limit (selling/customer.py
    → get_credit_limit) reads `credit_limit` directly, so as long as
    that field equals the sum, the existing block-on-overrun behaviour
    on Sales Order / Sales Invoice / Delivery Note / Journal Entry stays
    intact — no patch to ERPNext core needed.
    """
    for row in (doc.get("credit_limits") or []):
        insured = flt(row.get("custom_insured_limit"))
        internal = flt(row.get("custom_internal_limit"))
        row.credit_limit = insured + internal


# ── Server Script: "alias" ──
# DocType Event: Customer, Before Validate
def validate_alias(doc, method=None):
    """Prevent duplicate customer_name + alias combinations."""
    if doc.alias:
        duplicate = frappe.db.exists({
            "doctype": "Customer",
            "customer_name": doc.customer_name,
            "alias": doc.alias,
            "name": ["!=", doc.name],
        })
        if duplicate:
            frappe.throw("Same customer name already exist with same alias")


def after_insert(doc, method=None):
	"""When a Customer is created from a Lead, copy address/contact links and contact details."""
	lead_name = doc.lead_name
	if not lead_name:
		return

	_link_addresses_from_lead(doc, lead_name)
	_link_contacts_from_lead(doc, lead_name)
	_copy_contact_details_from_lead(doc, lead_name)


def _link_addresses_from_lead(doc, lead_name):
	"""Add Customer dynamic link to all addresses linked to the Lead."""
	addresses = frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Lead", "link_name": lead_name, "parenttype": "Address"},
		fields=["parent"],
	)
	for addr in addresses:
		address_doc = frappe.get_doc("Address", addr.parent)
		if not address_doc.has_link("Customer", doc.name):
			address_doc.append("links", {
				"link_doctype": "Customer",
				"link_name": doc.name,
				"link_title": doc.customer_name,
			})
			address_doc.save(ignore_permissions=True)


def _link_contacts_from_lead(doc, lead_name):
	"""Add Customer dynamic link to all contacts linked to the Lead."""
	contacts = frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Lead", "link_name": lead_name, "parenttype": "Contact"},
		fields=["parent"],
	)
	for contact in contacts:
		contact_doc = frappe.get_doc("Contact", contact.parent)
		if not contact_doc.has_link("Customer", doc.name):
			contact_doc.append("links", {
				"link_doctype": "Customer",
				"link_name": doc.name,
				"link_title": doc.customer_name,
			})
			contact_doc.save(ignore_permissions=True)


def _copy_contact_details_from_lead(doc, lead_name):
	"""Copy custom_contact_details child table rows from Lead to Customer."""
	lead = frappe.get_doc("Lead", lead_name)
	if not lead.get("custom_contact_details"):
		return

	for row in lead.custom_contact_details:
		doc.append("custom_contact_details", {
			"salutation": row.salutation,
			"first_name": row.first_name,
			"last_name": row.last_name,
			"designation": row.designation,
			"department": row.department,
			"email": row.email,
			"mobile": row.mobile,
			"type": row.type,
		})

	doc.save(ignore_permissions=True)
