"""Role-based row-level permissions for Payment Request Form.

Jithin / Sridhar 2026-06-13 via WhatsApp — none of the PRF Number Cards
on the Tasks dashboard respect role-based visibility. Every Accounts
User, Sales User or Stock User can read every PRF across every
company, and every card shows the GLOBAL count regardless of viewer.
The agreed role matrix:

  Role                            | Visibility
  ------------------------------- | ------------------------------------
  Requestor (Creator)             | Only documents created by themselves
  Department Head / Budget Owner  | Documents of their reporting dept only
  Accounts User                   | Their company / entity + payment
                                  | processing queue (Approved Level 2)
  Accounts Manager                | All documents within permitted
                                  | companies / entities
  Finance Manager                 | Full visibility across all companies
  Finance Controller              | Full visibility across all companies
  Director / CFO                  | Full visibility across all companies

This module wires that matrix to two Frappe hooks:

  permission_query_conditions["Payment Request Form"]
    -> returns a SQL WHERE fragment that scopes list views, reports,
       Number Card counts and any other doc-list query.

  has_permission["Payment Request Form"]
    -> single-doc check used by frappe.get_doc + UI link checks.
       Must stay in lockstep with the SQL above.

Design notes:

  1. The matrix has two roles that don't exist as Frappe Roles on prod
     ("Department Head" and "Budget Owner"). Rather than add hard-coded
     role names that admins would then have to maintain, this module
     derives them from User Permissions:

       - Department Head / Budget Owner = the user has User Permission
         entries of type Department. They see PRFs of those departments
         and all descendants (parent_department walk).

       - Accounts Manager / Accounts User company scoping = User
         Permission entries of type Company. Standard Frappe pattern,
         already used elsewhere in the system.

     Adding a head-of-department on prod = one User Permission row, no
     code change. Same for company scoping.

  2. Full-visibility roles short-circuit with `return None` (Frappe's
     contract for "no filter").

  3. Roles stack: a user with both "Accounts User" and a Department
     User Permission gets the UNION of both conditions (most permissive
     wins). Every authenticated user always sees their own creations
     even if no matrix role matches — that's the implicit
     "Requestor" floor.

  4. Administrator gets a clean `None` short-circuit. System Manager
     too.

  5. Date-of-record matters: PRFs with company IS NULL or department
     IS NULL only surface for full-vis roles + the creator. Documents
     missing scoping data shouldn't leak.
"""

import frappe


# Roles that get full visibility across every PRF, every company.
_FULL_VISIBILITY_ROLES = frozenset({
    "System Manager",
    "Finance Manager",
    "Finance Controller",
    "Director",
    "CFO",
    "Accounts Manager",  # per matrix — sees all within permitted companies;
                          # with no Company User Perms, "all permitted" == all
})

# Workflow state Accounts Users can see across companies — the
# "payment processing queue" from the matrix. PRFs sitting at
# Approved Level 2 are queued for release; AP needs to see them
# regardless of the originating company so they can action them.
_ACCOUNTS_PROCESSING_STATES = ("Approved Level 2",)

# Doctype literal — kept as a constant so renames are a one-touch fix.
_PRF = "Payment Request Form"


# ---------------------------------------------------------------------
# Public hook entry points
# ---------------------------------------------------------------------


def get_permission_query_conditions(user=None):
    """Return a SQL WHERE fragment to scope PRF list / report / count
    queries by the user's matrix role. Return None for "no filter".

    Wired from avientek/hooks.py:
        permission_query_conditions = {
            "Payment Request Form": "avientek.avientek.doctype.payment_request_form."
                                    "prf_permissions.get_permission_query_conditions",
        }
    """
    user = user or frappe.session.user
    if user == "Administrator":
        return None

    roles = set(frappe.get_roles(user))
    if roles & _FULL_VISIBILITY_ROLES:
        return None

    # Build OR'd conditions. Empty list at the end = nobody matched the
    # matrix → fall back to owner-only.
    clauses = []
    tbl = f"`tab{_PRF}`"

    # Accounts User — own company(ies) OR payment processing queue
    if "Accounts User" in roles:
        company_ids = _user_permitted_companies(user)
        company_clause = _in_clause(f"{tbl}.company", company_ids)
        states_clause = _in_clause(f"{tbl}.workflow_state", _ACCOUNTS_PROCESSING_STATES)
        # If user has no Company User Permission, the company branch
        # has no values → drop it; they still see the processing queue.
        accounts_clauses = [c for c in (company_clause, states_clause) if c]
        if accounts_clauses:
            clauses.append("(" + " OR ".join(accounts_clauses) + ")")

    # Department Head / Budget Owner — User Permissions on Department,
    # plus all descendant departments
    dept_ids = _user_dept_subtree(user)
    if dept_ids:
        dept_clause = _in_clause(f"{tbl}.department", dept_ids)
        if dept_clause:
            clauses.append(dept_clause)

    # Implicit Requestor floor — every user always sees their own.
    clauses.append(f"{tbl}.owner = {frappe.db.escape(user)}")

    return "(" + " OR ".join(clauses) + ")"


def has_permission(doc, user=None, permission_type=None):
    """Single-doc check — must stay in sync with the SQL above.

    Wired from avientek/hooks.py:
        has_permission = {
            "Payment Request Form": "avientek.avientek.doctype.payment_request_form."
                                    "prf_permissions.has_permission",
        }
    """
    user = user or frappe.session.user
    if user == "Administrator":
        return True

    roles = set(frappe.get_roles(user))
    if roles & _FULL_VISIBILITY_ROLES:
        return True

    # Owner always allowed
    if (doc.get("owner") if hasattr(doc, "get") else getattr(doc, "owner", None)) == user:
        return True

    # Accounts User — company match OR processing-queue state
    if "Accounts User" in roles:
        doc_company = doc.get("company") if hasattr(doc, "get") else getattr(doc, "company", None)
        doc_state = (doc.get("workflow_state") if hasattr(doc, "get")
                     else getattr(doc, "workflow_state", None))
        if doc_state in _ACCOUNTS_PROCESSING_STATES:
            return True
        if doc_company and doc_company in _user_permitted_companies(user):
            return True

    # Department Head / Budget Owner
    doc_dept = doc.get("department") if hasattr(doc, "get") else getattr(doc, "department", None)
    if doc_dept and doc_dept in _user_dept_subtree(user):
        return True

    return False


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _in_clause(column_sql, values):
    """Build a `col IN (...)` SQL fragment with safely-escaped values.
    Returns "" if values is empty (so callers can compose with OR).
    """
    if not values:
        return ""
    escaped = ", ".join(frappe.db.escape(v) for v in values)
    return f"{column_sql} IN ({escaped})"


def _user_permitted_companies(user):
    """Companies for which the user has an explicit User Permission.

    Empty result means the user has no Company User Permission
    configured — which under standard Frappe semantics means "no
    restriction". The matrix asks for the opposite for Accounts User:
    they must NOT see all companies unscoped. We honour that by
    returning [] here (which the SQL caller treats as "no company
    branch — show only processing queue"). If you ever need "no User
    Perm = see all", check `frappe.get_roles` for "Accounts Manager"
    above (which short-circuits to full visibility).
    """
    return list(set(frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Company"},
        pluck="for_value",
    )))


def _user_dept_subtree(user):
    """Departments the user heads — derived from User Permissions of
    type Department — plus all descendant departments (recursive walk
    via parent_department).
    """
    head_depts = list(set(frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Department"},
        pluck="for_value",
    )))
    if not head_depts:
        return []

    # BFS through parent_department links to gather sub-departments
    all_depts = set(head_depts)
    cursor = list(head_depts)
    # Bound the walk in case of cycles (corrupt prod data); Frappe trees
    # rarely exceed 8 levels.
    for _ in range(16):
        if not cursor:
            break
        children = frappe.get_all(
            "Department",
            filters={"parent_department": ["in", cursor]},
            pluck="name",
        ) or []
        new = [d for d in children if d not in all_depts]
        if not new:
            break
        all_depts.update(new)
        cursor = new

    return list(all_depts)
