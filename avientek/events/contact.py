"""Contact CRM tracking fields — client meeting 2026-09-08 (Rahul).

Rahul asked for the contact-details sections on Lead and Customer to be hidden
so that ALL contact data entry funnels into the Contact CRM. That only works if
Contact itself records who entered a contact and when — otherwise the
centralised list is untraceable. This module stamps:

  * custom_created_by — the creating user. Read-only, set once on insert.
  * custom_date       — defaults to today, but the user may change it.
  * custom_sales_person is keyed in by hand (no rule here); it sits directly
    above the standard `status` field.

The fields themselves are created in migrate.py (_create_contact_crm_fields);
this module holds the runtime rules.
"""
import frappe
from frappe.utils import today


def set_created_by(doc, method=None):
    """Stamp the creating user on the read-only 'Created By' field.

    before_insert, so it is set once and never overwritten — the same pattern
    as avientek.events.project.set_created_by."""
    if not doc.get("custom_created_by"):
        doc.custom_created_by = frappe.session.user


def set_default_date(doc, method=None):
    """Fall back to today when no Date was supplied.

    The field carries `default: "Today"`, which covers the form; this covers
    every other way a Contact is created (data import, the Lead → Customer
    conversion, API) where Frappe does NOT apply field defaults. Deliberately
    only on insert: the user is free to change the date afterwards, and
    Sridhar 2026-09-08 confirmed it stays editable for now (it may be made
    read-only later once the team has settled on how they use it)."""
    if not doc.get("custom_date"):
        doc.custom_date = today()
