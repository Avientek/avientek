# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt
"""
Project module enhancement (Rahul Prakash, 2026-08-22).

Adds a sales-pipeline layer to Project: a custom status
(custom_project_status) plus sales fields, and a Level-2 approval gate — once
a project is Approved, changing its status (to anything but Closed) or its
Expected Closing Date requires the "Project L2 Approver" role.

Client meeting 2026-09-08 (Rahul) adds one more rule, at the bottom of this
module: the budget figures are mirrored into read-only USD columns at a FROZEN
exchange rate.

The Focused Brands table on Project is keyed in by hand, exactly like the one
on Lead — an earlier auto-fetch from the customer's Lead was cancelled by the
client on 2026-09-10, so there is deliberately no brand logic here.

The custom fields themselves are created in migrate.py
(_create_project_enhancement_fields); this module holds the runtime rules.
"""
import frappe
from frappe import _
from frappe.utils import flt

PROJECT_L2_ROLE = "Project L2 Approver"
_APPROVED = "Approved"

# Roles that see EVERY project regardless of the sales-person scope
# (Rahul follow-up 2026-08-25, item 6).
_PROJECT_VISIBILITY_BYPASS_ROLES = {"System Manager", "Projects Manager"}
# Only read-like access is scoped; creation / editing one's own project is
# unaffected (a user can't open a project that isn't in their list anyway).
_PROJECT_SCOPED_PTYPES = {"read", "select", "email", "print", "export", "report"}


def set_created_by(doc, method=None):
    """Stamp the creating user on the read-only 'Created By' field (point 3).
    Runs on before_insert so it is set once and never overwritten."""
    if not doc.get("custom_created_by"):
        doc.custom_created_by = frappe.session.user


def set_parent_sales_person(doc, method=None):
    """Follow-up item 1: auto-fill the read-only 'Parent Sales Person' from the
    Assigned Sales Person's parent in the Sales Person tree, so it always
    reflects the current hierarchy (and feeds the visibility rule, item 6).
    Cleared when no Assigned Sales Person is set."""
    assigned = doc.get("custom_sales_person")
    doc.custom_parent_sales_person = (
        frappe.db.get_value("Sales Person", assigned, "parent_sales_person")
        if assigned else None
    )


# ── Item 6: project visibility by sales person / creator ──────────────
def _project_sales_persons(user):
    """Sales Persons this user is scoped to, via their Sales Person User
    Permissions (Sales Person has no user_id on this site). Empty list means
    the user has NO sales-person restriction → full visibility."""
    from avientek.api.user_permission_utils import get_user_permission_values
    return get_user_permission_values(user, "Sales Person")


def _project_visibility_bypass(user):
    if user == "Administrator":
        return True
    return bool(_PROJECT_VISIBILITY_BYPASS_ROLES & set(frappe.get_roles(user)))


def project_permission_query(user=None):
    """List-view scope (item 6): a restricted sales user sees a Project only
    when its Assigned Sales Person / Parent Sales Person / Project by is one of
    their permitted Sales Persons, OR they created it. Bypassed for Admin /
    System Manager / Projects Manager / users with no Sales Person restriction.
    """
    user = user or frappe.session.user
    if _project_visibility_bypass(user):
        return ""
    sps = _project_sales_persons(user)
    if not sps:
        return ""  # no Sales Person restriction → full visibility
    sp_list = ", ".join(frappe.db.escape(s) for s in sps)
    esc_user = frappe.db.escape(user)
    return (
        "(`tabProject`.`custom_sales_person` in ({sp})"
        " or `tabProject`.`custom_parent_sales_person` in ({sp})"
        " or `tabProject`.`custom_project_by` in ({sp})"
        " or `tabProject`.`custom_created_by` = {u})"
    ).format(sp=sp_list, u=esc_user)


def has_project_permission(doc, ptype=None, user=None):
    """Single-doc gate mirroring project_permission_query, for direct URL /
    link access. Only read-like ptypes are scoped; creation and other actions
    are left to the standard role permissions."""
    user = user or frappe.session.user
    if ptype and ptype not in _PROJECT_SCOPED_PTYPES:
        return True
    if _project_visibility_bypass(user):
        return True
    sps = set(_project_sales_persons(user))
    if not sps:
        return True
    if doc.get("custom_created_by") == user:
        return True
    for fn in ("custom_sales_person", "custom_parent_sales_person", "custom_project_by"):
        val = doc.get(fn)
        if val and val in sps:
            return True
    return False


def enforce_l2_approval(doc, method=None):
    """Points 8 & 11: once a Project reaches 'Approved' (custom_project_status),
    changing its status to anything other than 'Closed', or changing its
    Expected Closing Date, requires Level 2 approval — the user must hold the
    'Project L2 Approver' role. System Manager / Administrator bypass, the same
    way the other Avientek approval gates do.

    Only fires when the project WAS Approved before this save; a project being
    moved INTO Approved, or edited in any other state, is unaffected.
    """
    if doc.is_new():
        return
    before = doc.get_doc_before_save()
    if not before:
        return
    if (before.get("custom_project_status") or "") != _APPROVED:
        return

    user = frappe.session.user
    if user == "Administrator":
        return
    roles = set(frappe.get_roles(user))
    if "System Manager" in roles or PROJECT_L2_ROLE in roles:
        return

    new_status = doc.get("custom_project_status") or ""
    if new_status != _APPROVED and new_status != "Closed":
        frappe.throw(
            _("Changing an Approved project's status to <b>{0}</b> needs Level 2 "
              "approval (the <b>{1}</b> role).").format(new_status, PROJECT_L2_ROLE),
            title=_("Level 2 Approval Required"),
        )

    if (before.get("custom_expected_closing_date") or None) != (
        doc.get("custom_expected_closing_date") or None
    ):
        frappe.throw(
            _("Changing an Approved project's Expected Closing Date needs Level 2 "
              "approval (the <b>{0}</b> role).").format(PROJECT_L2_ROLE),
            title=_("Level 2 Approval Required"),
        )


# ══════════════════════════════════════════════════════════════════════
# Client meeting 2026-09-08 (Rahul) — Budget in USD
# ══════════════════════════════════════════════════════════════════════
USD = "USD"

def _company_currency(company):
    """Company default currency (AED for the Avientek companies). Empty when
    the project has no company yet — a brand-new unsaved doc."""
    if not company:
        return None
    return frappe.get_cached_value("Company", company, "default_currency")


def _usd_rate(company_currency, on_date=None):
    """Company currency per 1 USD (e.g. 3.6725 AED = 1 USD).

    Stored on the project so the USD figures stay FROZEN at the rate that was
    live when the budget was last entered — Rahul 2026-09-08: reporting must
    not drift with the market. Returns 0.0 when no rate can be resolved, and
    the caller then leaves the USD fields untouched rather than writing a
    number we cannot stand behind.
    """
    if not company_currency:
        return 0.0
    if company_currency == USD:
        return 1.0
    try:
        from erpnext.setup.utils import get_exchange_rate
        return flt(get_exchange_rate(USD, company_currency, on_date))
    except Exception:
        # No Currency Exchange record / provider unreachable. Not fatal — the
        # project must still save.
        frappe.log_error(
            title="Project budget USD conversion: exchange rate lookup failed",
            message=frappe.get_traceback(),
        )
        return 0.0


def _budget_inputs_changed(doc):
    """True when the frozen rate must be re-fetched.

    The ONLY triggers are: a new project, a change to either budget figure, or
    a change of company currency (which would otherwise leave the stored rate
    pointing at the wrong currency pair). Editing anything else on the project
    — status, sales person, dates — deliberately leaves the rate alone.
    """
    if doc.is_new():
        return True
    before = doc.get_doc_before_save()
    if not before:
        return True
    if flt(before.get("custom_budget_amount")) != flt(doc.get("custom_budget_amount")):
        return True
    if flt(before.get("custom_budget_value")) != flt(doc.get("custom_budget_value")):
        return True
    # Company (and therefore company currency) switched under a stored rate.
    if (before.get("custom_company_currency") or "") != (
        doc.get("custom_company_currency") or ""
    ):
        return True
    return False


def set_budget_usd(doc, method=None):
    """Rahul 2026-09-08: Budget Amount / Budget Value are keyed in the COMPANY
    currency (AED); mirror both into read-only USD columns.

    Conversion is ALWAYS company currency → USD, never the document currency.

    The rate is frozen: it is fetched when a budget figure is entered and then
    stored on the project, so the USD columns are stable for reporting. To pick
    up a newer rate the user re-enters a budget figure and saves — that
    instruction is on the field descriptions (see migrate.py) so it is visible
    on the form itself.
    """
    company_currency = _company_currency(doc.get("company"))
    # Stamped so the Currency fields render in the right symbol, and so a
    # company switch can be detected on the next save.
    doc.custom_company_currency = company_currency or ""

    amount = flt(doc.get("custom_budget_amount"))
    value = flt(doc.get("custom_budget_value"))

    if not amount and not value:
        doc.custom_exchange_rate = 0
        doc.custom_budget_amount_usd = 0
        doc.custom_budget_value_usd = 0
        return

    rate = flt(doc.get("custom_exchange_rate"))
    if _budget_inputs_changed(doc) or rate <= 0:
        fresh = _usd_rate(company_currency, doc.get("expected_start_date"))
        if fresh > 0:
            rate = fresh
            doc.custom_exchange_rate = rate

    if rate <= 0:
        # Leave the USD columns as they are (blank on a new project) and tell
        # the user why, without blocking the save.
        frappe.msgprint(
            _("Could not find a {0} → USD exchange rate, so the USD budget "
              "columns were not updated. Add a Currency Exchange record and "
              "re-enter the budget to fill them in.").format(company_currency or "?"),
            title=_("Exchange Rate Not Found"),
            indicator="orange",
        )
        return

    doc.custom_budget_amount_usd = flt(
        amount / rate, doc.precision("custom_budget_amount_usd"))
    doc.custom_budget_value_usd = flt(
        value / rate, doc.precision("custom_budget_value_usd"))


# ── Form-side helpers (public/js/project.js) ──────────────────────────
@frappe.whitelist()
def get_budget_usd_preview(company, budget_amount=0, budget_value=0):
    """Live preview for the form: the SAME numbers set_budget_usd will store,
    so the user sees the conversion the moment they leave the budget field
    instead of only after a save. Python stays the single source of truth for
    the arithmetic."""
    company_currency = _company_currency(company)
    rate = _usd_rate(company_currency)
    if rate <= 0:
        return {"company_currency": company_currency, "exchange_rate": 0}
    return {
        "company_currency": company_currency,
        "exchange_rate": rate,
        "budget_amount_usd": flt(flt(budget_amount) / rate, 2),
        "budget_value_usd": flt(flt(budget_value) / rate, 2),
    }


# ══════════════════════════════════════════════════════════════════════
# Contacts on the Project, Customer-style — Sridhar 2026-09-11
# ══════════════════════════════════════════════════════════════════════
# Replaces the 2026-09-10 single Contact link + write-back fields. The Project
# now works exactly like the Customer's "Address & Contact" section: a list of
# every Contact linked to the project (through the Contact's `links` Dynamic
# Link table) with a "New Contact" button, all rendered by Frappe's own
# frappe.contacts.render_address_and_contact. The Contact record is the only
# place the details live, so there is nothing to keep in sync.
#
# Two things make Frappe's machinery treat Project like Customer:
#   * an HTML field named exactly `contact_html` (created in migrate.py) — the
#     renderer draws into it, and the Contact form's Link Document Type picker
#     only offers doctypes that carry a field of that name;
#   * `contact_list` in the form's __onload, loaded below.


def load_contacts(doc, method=None):
    """onload: the same contact list Customer.onload builds via
    load_address_and_contact — contacts only, Project has no addresses."""
    from frappe.contacts.doctype.contact.contact import get_contact_display_list
    doc.set_onload("contact_list", get_contact_display_list(doc.doctype, doc.name))


def unlink_contacts(doc, method=None):
    """on_trash: drop this project from its contacts' Links table so the
    delete isn't blocked by "Project X is linked with Contact Y".

    Deliberately gentler than Customer, which DELETES a contact whose only
    link is the customer (delete_contact_and_address). A contact made for a
    project is still a real person in the CRM, so it is kept, just unlinked."""
    frappe.db.delete("Dynamic Link", {
        "parenttype": "Contact",
        "link_doctype": "Project",
        "link_name": doc.name,
    })
