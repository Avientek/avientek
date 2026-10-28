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
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.model import no_value_fields, table_fields
from frappe.utils import (
    add_months, add_to_date, cint, cstr, escape_html, flt, format_datetime,
    formatdate, get_datetime, get_fullname, getdate, now_datetime, nowdate,
)

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
    """'Parent Sales Person' is a user-selectable field (ticket #0522) —
    independent of the Assigned Sales Person, and pickable even when no
    Assigned Sales Person is set. This hook only fills it as a CONVENIENCE:
    when the user leaves it blank AND an Assigned Sales Person is set, derive
    it from that SP's parent in the Sales Person tree. A value the user chose
    is never overwritten or cleared (that was the old read-only behaviour).
    Both feed the visibility rule (project_permission_query)."""
    if doc.get("custom_parent_sales_person"):
        return  # user (or a prior fill) set it — leave it alone
    assigned = doc.get("custom_sales_person")
    if assigned:
        doc.custom_parent_sales_person = frappe.db.get_value(
            "Sales Person", assigned, "parent_sales_person"
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


# ── Rahul 2026-10-13: no duplicate project names ──────────────────────
# ERPNext already puts a UNIQUE index on Project.project_name (all companies,
# every status), but a clash surfaced as a raw "Duplicate entry" database
# error. This check runs first and says which project holds the name.
def prevent_duplicate_project_name(doc, method=None):
    """Block saving a project whose name, ignoring case and surrounding
    spaces, is already used by another project. Surrounding spaces are
    trimmed off the saved name so "Acme" and " Acme " cannot both exist."""
    name = (doc.get("project_name") or "").strip()
    if not name:
        return
    doc.project_name = name

    clash = frappe.db.sql(
        """SELECT name, company
           FROM `tabProject`
           WHERE LOWER(TRIM(project_name)) = %(pn)s AND name != %(me)s
           LIMIT 1""",
        {"pn": name.lower(), "me": doc.name or ""},
    )
    if clash:
        other, company = clash[0]
        # custom_project_status is created in after_migrate — guard so a
        # fresh install (before the first migrate) doesn't hit a missing column.
        status = (
            frappe.db.get_value("Project", other, "custom_project_status")
            if frappe.db.has_column("Project", "custom_project_status") else ""
        ) or ""
        frappe.throw(
            _("A project named <b>{0}</b> already exists: {1} ({2}{3}). "
              "Please use a different name.").format(
                frappe.utils.escape_html(name),
                frappe.utils.get_link_to_form("Project", other),
                company or "",
                f", {status}" if status else ""),
            title=_("Duplicate Project Name"),
        )


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
    # An L2 approver allowed this user's edit request (enforce_edit_lock).
    if doc.flags.project_edit_unlocked:
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
# Rahul 2026-10-13 (point 13) — edit lock on Approved / Closed projects
# ══════════════════════════════════════════════════════════════════════
# An Approved or Closed project whose Expected Closing Date is within N months
# before or after today (Avientek Settings > Lock Window, default 6) is
# read-only. Project L2 Approvers and System Managers still edit it directly.
# Anyone else clicks "Request Edit"; once an approver clicks "Allow Edit" the
# requester gets ONE save within 24 hours. Approved -> Closed needs no approval.
_LOCKED_STATUSES = (_APPROVED, "Closed")
_DEFAULT_LOCK_MONTHS = 6
_UNLOCK_HOURS = 24
# Request / unlock state. Written only by the whitelisted methods below, never
# from the form, so validate always takes these from the database.
_LOCK_STATE_FIELDS = (
    "custom_edit_requested_by",
    "custom_edit_request_reason",
    "custom_edit_unlocked_for",
    "custom_edit_unlocked_until",
)
_IGNORED_CHANGE_FIELDS = {"modified", "modified_by", *_LOCK_STATE_FIELDS}
_REQUEST_TODO_PREFIX = "Edit request for Project"


def _lock_months():
    months = 0
    if frappe.get_meta("Avientek Settings").has_field("project_lock_months"):
        months = frappe.db.get_single_value("Avientek Settings", "project_lock_months")
    return cint(months) or _DEFAULT_LOCK_MONTHS


def _is_locked(d):
    """True when project data `d` (its SAVED state) falls under the lock. A
    project with no Expected Closing Date is not locked."""
    if (d.get("custom_project_status") or "") not in _LOCKED_STATUSES:
        return False
    closing = d.get("custom_expected_closing_date")
    if not closing:
        return False
    months = _lock_months()
    today = getdate(nowdate())
    return add_months(today, -months) <= getdate(closing) <= add_months(today, months)


def _is_lock_approver(user):
    if user == "Administrator":
        return True
    roles = set(frappe.get_roles(user))
    return "System Manager" in roles or PROJECT_L2_ROLE in roles


def _unlocked_for(d, user):
    until = d.get("custom_edit_unlocked_until")
    return bool(d.get("custom_edit_unlocked_for") == user and until
                and get_datetime(until) > now_datetime())


def _norm(fieldtype, value):
    """One comparable form per value, so a date string from the form equals
    the date object from the database and 0 equals blank."""
    if value in (None, ""):
        return None
    if fieldtype in ("Int", "Check"):
        return cint(value) or None
    if fieldtype in ("Float", "Currency", "Percent"):
        return flt(value) or None
    if fieldtype == "Date":
        return str(getdate(value))
    if fieldtype == "Datetime":
        return str(get_datetime(value))
    return cstr(value)


def _editable_columns(meta):
    return [df for df in meta.fields
            if df.fieldtype not in no_value_fields and df.fieldtype not in table_fields
            and not df.read_only and not df.hidden
            and df.fieldname not in _IGNORED_CHANGE_FIELDS]


def _editable_values(doc):
    """What a user can change on the form: every field except read-only,
    hidden and layout ones; child tables reduced to their editable columns.
    A recomputed total (ERPNext update_costing) or a server stamp therefore
    never counts as a user edit."""
    out = {df.fieldname: _norm(df.fieldtype, doc.get(df.fieldname))
           for df in _editable_columns(doc.meta)}
    for df in doc.meta.get_table_fields():
        if df.read_only or df.hidden:
            continue
        cols = _editable_columns(frappe.get_meta(df.options))
        out[df.fieldname] = [
            tuple(_norm(c.fieldtype, row.get(c.fieldname)) for c in cols)
            for row in (doc.get(df.fieldname) or [])
        ]
    return out


def enforce_edit_lock(doc, method=None):
    """validate: block edits to a locked project unless the user is an
    approver or holds an unused approval. Runs first in validate, before any
    hook that stamps values on the doc."""
    if doc.is_new() or doc.flags.ignore_project_edit_lock:
        return
    if frappe.flags.in_migrate or frappe.flags.in_patch or frappe.flags.in_install:
        return
    before = doc.get_doc_before_save()
    if not before:
        return
    for f in _LOCK_STATE_FIELDS:
        if doc.meta.has_field(f):
            doc.set(f, before.get(f))
    if not _is_locked(before):
        return

    user = frappe.session.user
    if _is_lock_approver(user):
        return
    if _unlocked_for(before, user):
        # One save per approval: use it up now. Also lets enforce_l2_approval
        # through for the status / closing-date change.
        doc.flags.project_edit_unlocked = True
        doc.custom_edit_unlocked_for = None
        doc.custom_edit_unlocked_until = None
        doc.add_comment("Comment", _("Edited with L2 approval."))
        return

    old, new = _editable_values(before), _editable_values(doc)
    changed = [f for f in new if old.get(f) != new[f]]
    if not changed:
        return
    if (changed == ["custom_project_status"]
            and before.get("custom_project_status") == _APPROVED
            and doc.get("custom_project_status") == "Closed"):
        return

    frappe.throw(
        _("This project is <b>{0}</b> with Expected Closing Date {1}, so it is "
          "locked for editing.<br>Changed: {2}.<br>Click <b>Request Edit</b> "
          "to ask a Project L2 Approver.").format(
            before.get("custom_project_status"),
            formatdate(before.get("custom_expected_closing_date")),
            ", ".join(_(doc.meta.get_label(f)) for f in changed[:6])
            + (" …" if len(changed) > 6 else "")),
        title=_("Project Locked"),
    )


def load_edit_lock(doc, method=None):
    """onload: lock state for the form buttons and banner (project.js)."""
    if doc.is_new() or not _is_locked(doc):
        doc.set_onload("edit_lock", {"locked": False})
        return
    user = frappe.session.user
    requester = doc.get("custom_edit_requested_by")
    doc.set_onload("edit_lock", {
        "locked": True,
        "months": _lock_months(),
        "is_approver": _is_lock_approver(user),
        "unlocked_for_me": _unlocked_for(doc, user),
        "unlocked_until": doc.get("custom_edit_unlocked_until"),
        "requested_by": requester,
        "requested_by_name": get_fullname(requester) if requester else "",
        "request_reason": doc.get("custom_edit_request_reason"),
    })


def _approver_users():
    return frappe.db.sql_list(
        """SELECT DISTINCT u.name FROM `tabHas Role` hr
           JOIN `tabUser` u ON u.name = hr.parent
           WHERE hr.parenttype = 'User' AND hr.role = %s AND u.enabled = 1
             AND u.name NOT IN ('Administrator', 'Guest')""",
        PROJECT_L2_ROLE,
    )


def _notify(users, project, subject):
    enqueue_create_notification(users, {
        "type": "Alert",
        "document_type": "Project",
        "document_name": project,
        "subject": subject,
        "from_user": frappe.session.user,
    })


def _close_request_todos(project, requester, status):
    for name in frappe.get_all("ToDo", pluck="name", filters={
        "reference_type": "Project", "reference_name": project,
        "status": "Open", "assigned_by": requester,
        "description": ["like", f"{_REQUEST_TODO_PREFIX}%"],
    }):
        todo = frappe.get_doc("ToDo", name)
        todo.status = status
        todo.save(ignore_permissions=True)


@frappe.whitelist()
def request_project_edit(project, reason):
    doc = frappe.get_doc("Project", project)
    doc.check_permission("write")
    user = frappe.session.user
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Please enter the reason for the edit."))
    if not _is_locked(doc) or _is_lock_approver(user):
        frappe.throw(_("You can edit this project directly. Please reload the page."))
    pending = doc.get("custom_edit_requested_by")
    if pending and pending != user:
        frappe.throw(_("{0} already has an edit request waiting on this project.")
                     .format(get_fullname(pending)))
    approvers = _approver_users()
    if not approvers:
        frappe.throw(_("No user has the <b>{0}</b> role yet. Please ask your "
                       "System Manager to assign it.").format(PROJECT_L2_ROLE))

    frappe.db.set_value("Project", project, {
        "custom_edit_requested_by": user,
        "custom_edit_request_reason": reason,
        "custom_edit_unlocked_for": None,
        "custom_edit_unlocked_until": None,
    }, update_modified=False)

    description = "{0} {1} ({2}) from {3}: {4}".format(
        _REQUEST_TODO_PREFIX, project, doc.project_name, get_fullname(user),
        escape_html(reason))
    for approver in approvers:
        if frappe.db.exists("ToDo", {
            "allocated_to": approver, "reference_type": "Project",
            "reference_name": project, "status": "Open", "assigned_by": user,
        }):
            continue
        frappe.get_doc({
            "doctype": "ToDo",
            "allocated_to": approver,
            "assigned_by": user,
            "reference_type": "Project",
            "reference_name": project,
            "description": description,
            "priority": "Medium",
        }).insert(ignore_permissions=True)
    _notify(approvers, project, _("{0} requested approval to edit Project {1}")
            .format(get_fullname(user), project))
    doc.add_comment("Comment", _("Requested approval to edit: {0}").format(escape_html(reason)))
    return approvers


def _pending_request(project):
    if not _is_lock_approver(frappe.session.user):
        frappe.throw(_("Only a {0} can do this.").format(PROJECT_L2_ROLE),
                     frappe.PermissionError)
    doc = frappe.get_doc("Project", project)
    requester = doc.get("custom_edit_requested_by")
    if not requester:
        frappe.throw(_("There is no edit request waiting on this project."))
    return doc, requester


@frappe.whitelist()
def allow_project_edit(project):
    doc, requester = _pending_request(project)
    until = add_to_date(now_datetime(), hours=_UNLOCK_HOURS)
    frappe.db.set_value("Project", project, {
        "custom_edit_requested_by": None,
        "custom_edit_request_reason": None,
        "custom_edit_unlocked_for": requester,
        "custom_edit_unlocked_until": until,
    }, update_modified=False)
    _close_request_todos(project, requester, "Closed")
    msg = _("Allowed {0} to edit this project once, until {1}.").format(
        get_fullname(requester), format_datetime(until))
    doc.add_comment("Comment", msg)
    _notify([requester], project, _("Your edit request for Project {0} was approved. "
                                    "You can save it once, until {1}.")
            .format(project, format_datetime(until)))
    return until


@frappe.whitelist()
def decline_project_edit(project, reason=None):
    doc, requester = _pending_request(project)
    frappe.db.set_value("Project", project, {
        "custom_edit_requested_by": None,
        "custom_edit_request_reason": None,
    }, update_modified=False)
    _close_request_todos(project, requester, "Cancelled")
    reason = escape_html((reason or "").strip())
    doc.add_comment("Comment", _("Declined the edit request from {0}.{1}").format(
        get_fullname(requester), f" {reason}" if reason else ""))
    _notify([requester], project, _("Your edit request for Project {0} was declined.")
            .format(project))


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


def _brand_values(d):
    """(brand, value) pairs of the Focused Brands rows that carry a Value."""
    return sorted(
        ((r.get("brand") or ""), flt(r.get("value")))
        for r in (d.get("custom_focused_brands") or [])
        if flt(r.get("value"))
    )


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
    # Focused Brands values are converted at the same frozen rate — entering
    # or changing a brand Value refreshes the rate exactly like a budget figure.
    if _brand_values(before) != _brand_values(doc):
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

    brand_rows = doc.get("custom_focused_brands") or []
    has_brand_value = any(flt(r.get("value")) for r in brand_rows)

    if not amount and not value and not has_brand_value:
        doc.custom_exchange_rate = 0
        doc.custom_budget_amount_usd = 0
        doc.custom_budget_value_usd = 0
        for r in brand_rows:
            r.value_usd = 0
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
    # 2026-09-24: Focused Brands Value -> Value (USD), same frozen rate.
    for r in brand_rows:
        r.value_usd = flt(flt(r.get("value")) / rate, r.precision("value_usd"))


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
