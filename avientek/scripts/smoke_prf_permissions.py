"""Smoke test for the PRF role-based visibility hook.

Jithin / Sridhar 2026-06-13 — the dashboard Number Cards (PRF Pending
Authorization / Fin. Manager / Director / Release / Rejected) showed
GLOBAL counts because no permission_query_conditions hook existed on
Payment Request Form. The fix in
`avientek.avientek.doctype.payment_request_form.prf_permissions`
implements the agreed role matrix:

  Requestor (default)           → owner = self
  Department Head / Budget Owner→ department IN <User Perm tree>
  Accounts User                 → company IN <User Perm companies>
                                  OR workflow_state = 'Approved Level 2'
  Accounts Manager              → full visibility (matrix says "all within
                                  permitted companies"; Frappe's User Perm
                                  filter handles company scoping on top)
  Finance Manager / Controller  → full visibility
  Director / CFO                → full visibility
  System Manager / Administrator→ full visibility

This smoke locks in three layers:

  1. The SQL fragment is well-formed and safely escapes user input
     (no SQL injection via username, no SQL injection via department
     name with quotes / backticks).

  2. Each matrix role returns the right shape: None for full-vis,
     a clause for scoped, and the owner-floor present in every
     non-None result.

  3. The same predicate ALSO holds in has_permission for single-doc
     reads (must stay in lockstep with the SQL — otherwise a list
     view shows a doc that the form refuses to open, which is a UX
     bug we've hit before).

Usage:
    bench --site avientekv21.local execute \\
        avientek.scripts.smoke_prf_permissions.run
"""

import frappe


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


def _import():
    from avientek.avientek.doctype.payment_request_form import prf_permissions as pp
    return pp


# ---------------- helper: fake user creation ------------------------


def _ensure_role(name):
    if not frappe.db.exists("Role", name):
        r = frappe.new_doc("Role")
        r.role_name = name
        r.insert(ignore_permissions=True)


def _ensure_user(email, roles):
    """Create (or reset) a test user with exactly the given role set.
    Returns the user's email (== name)."""
    for r in roles:
        _ensure_role(r)

    if frappe.db.exists("User", email):
        u = frappe.get_doc("User", email)
        # Clear existing roles then re-add — keeps the test deterministic
        u.set("roles", [])
        for r in roles:
            u.append("roles", {"role": r})
        u.save(ignore_permissions=True)
    else:
        u = frappe.new_doc("User")
        u.email = email
        u.first_name = "Smoke"
        u.last_name = email.split("@")[0]
        u.send_welcome_email = 0
        u.enabled = 1
        for r in roles:
            u.append("roles", {"role": r})
        u.insert(ignore_permissions=True)

    return email


def _set_user_permission(user, allow, for_value):
    """Idempotent: add a User Permission row if not present."""
    if frappe.db.exists("User Permission",
                        {"user": user, "allow": allow, "for_value": for_value}):
        return
    up = frappe.new_doc("User Permission")
    up.user = user
    up.allow = allow
    up.for_value = for_value
    up.apply_to_all_doctypes = 1
    up.insert(ignore_permissions=True)


def _clear_user_permissions(user):
    frappe.db.delete("User Permission", {"user": user})


# ---------------- structural / wiring -------------------------------


def _check_hook_wired():
    print()
    print("=== Hook wiring: hooks.py registers PRF perms ===")
    hooks = frappe.get_hooks()
    pqc = hooks.get("permission_query_conditions", {}).get("Payment Request Form", [])
    hp = hooks.get("has_permission", {}).get("Payment Request Form", [])

    target_pqc = "avientek.avientek.doctype.payment_request_form.prf_permissions.get_permission_query_conditions"
    target_hp = "avientek.avientek.doctype.payment_request_form.prf_permissions.has_permission"
    if target_pqc not in pqc:
        _fail(f"permission_query_conditions[Payment Request Form] = {pqc}, expected to contain {target_pqc}")
    if target_hp not in hp:
        _fail(f"has_permission[Payment Request Form] = {hp}, expected to contain {target_hp}")
    _ok("both hooks registered in hooks.py and visible to frappe.get_hooks()")


# ---------------- behavioural: per-role SQL fragment ----------------


def _check_administrator_no_filter():
    print()
    print("=== Administrator → no filter ===")
    pp = _import()
    sql = pp.get_permission_query_conditions(user="Administrator")
    if sql is not None:
        _fail(f"Administrator must short-circuit to None, got {sql!r}")
    _ok("Administrator: None (no filter)")


def _check_full_visibility_roles():
    print()
    print("=== Full-vis roles short-circuit to None ===")
    pp = _import()
    for role in ("Finance Manager", "Finance Controller", "Director",
                 "System Manager", "Accounts Manager"):
        u = _ensure_user(f"smoke.fullvis.{role.lower().replace(' ', '_')}@avientek.test", [role])
        sql = pp.get_permission_query_conditions(user=u)
        if sql is not None:
            _fail(f"role {role!r}: expected None, got {sql!r}")
    _ok("Finance Manager / Controller / Director / System Manager / "
        "Accounts Manager → None")


def _check_requestor_floor_only():
    print()
    print("=== Plain user (no matrix role) → owner = self ===")
    pp = _import()
    u = _ensure_user("smoke.requestor@avientek.test", [])
    sql = pp.get_permission_query_conditions(user=u)
    if sql is None:
        _fail(f"requestor must be scoped, got None")
    if "owner = " not in sql:
        _fail(f"requestor SQL missing owner = clause: {sql!r}")
    if frappe.db.escape(u) not in sql:
        _fail(f"requestor SQL missing the escaped username: {sql!r}")
    # Must NOT have company / department / state branches
    for bad in ("company IN", "department IN", "workflow_state"):
        if bad in sql:
            _fail(f"requestor leaked {bad!r} clause: {sql!r}")
    _ok(f"requestor: owner-only floor → {sql}")


def _check_accounts_user_with_company_perm():
    print()
    print("=== Accounts User + Company User Perm → company OR state OR owner ===")
    pp = _import()
    u = _ensure_user("smoke.accuser.company@avientek.test", ["Accounts User"])
    _clear_user_permissions(u)
    _set_user_permission(u, "Company", "Avientek FZCO")
    try:
        sql = pp.get_permission_query_conditions(user=u)
    finally:
        _clear_user_permissions(u)
    if sql is None:
        _fail("Accounts User must be scoped, got None")
    if "Avientek FZCO" not in sql:
        _fail(f"missing FZCO company clause: {sql}")
    if "Approved Level 2" not in sql:
        _fail(f"missing payment-processing-queue clause: {sql}")
    if "owner = " not in sql:
        _fail(f"missing owner floor: {sql}")
    _ok(f"Accounts User: company-scoped + processing queue + owner floor")


def _check_accounts_user_no_company_perm():
    print()
    print("=== Accounts User + NO Company User Perm → state OR owner ===")
    pp = _import()
    u = _ensure_user("smoke.accuser.nocomp@avientek.test", ["Accounts User"])
    _clear_user_permissions(u)
    sql = pp.get_permission_query_conditions(user=u)
    if sql is None:
        _fail("Accounts User without User Perm must still be scoped, got None")
    if "company IN" in sql:
        _fail(f"Accounts User without User Perm leaked empty company clause: {sql}")
    if "Approved Level 2" not in sql:
        _fail(f"missing payment-processing-queue clause: {sql}")
    if "owner = " not in sql:
        _fail(f"missing owner floor: {sql}")
    _ok(f"Accounts User w/o User Perm: processing queue + owner floor only")


def _check_dept_head_with_dept_perm_and_subtree():
    print()
    print("=== Dept Head w/ Department User Perm → dept subtree clause ===")
    pp = _import()

    # Use existing prod-fixture departments rather than creating new
    # ones — Department.insert requires HR-module mandatories that
    # vary across sites and we don't want the smoke to depend on them.
    # We just need ONE department with at least one child for the
    # subtree-walk assertion.
    # Pick a group Department that actually HAS children — many group
    # depts on this site are empty stubs. Direct SQL is cheaper than
    # iterating frappe.get_all per candidate.
    parent_rows = frappe.db.sql(
        """
        SELECT p.name, COUNT(c.name) AS n_children
        FROM `tabDepartment` p
        LEFT JOIN `tabDepartment` c ON c.parent_department = p.name
        WHERE p.is_group = 1
        GROUP BY p.name
        HAVING n_children > 0
        ORDER BY n_children DESC
        LIMIT 1
        """,
        as_dict=True,
    )
    if not parent_rows:
        print("  (skipped — no group Department with children on site)")
        return
    parent = parent_rows[0]["name"]
    children = frappe.get_all("Department",
        filters={"parent_department": parent}, pluck="name", limit=2)
    child = children[0]

    u = _ensure_user("smoke.depthead@avientek.test", [])
    _clear_user_permissions(u)
    _set_user_permission(u, "Department", parent)
    try:
        sql = pp.get_permission_query_conditions(user=u)
    finally:
        _clear_user_permissions(u)

    if sql is None:
        _fail("Dept Head must be scoped, got None")
    if "department IN" not in sql:
        _fail(f"missing department IN clause: {sql}")
    if parent not in sql:
        _fail(f"parent dept {parent!r} missing from clause: {sql}")
    if child not in sql:
        _fail(
            f"child dept {child!r} NOT walked into clause: {sql}. "
            "Subtree expansion broken — head would only see direct dept, "
            "matrix says reporting dept (recursive)."
        )
    if "owner = " not in sql:
        _fail(f"missing owner floor: {sql}")
    _ok(f"Dept Head: {parent!r} + {len(children)} child(ren) + owner floor")


def _check_sql_injection_safe():
    print()
    print("=== SQL injection: hostile username escaped ===")
    pp = _import()
    # Frappe's User doctype validates email format and rejects
    # characters like single-quote / backticks, so we can't actually
    # CREATE a hostile user. We don't need to — get_permission_query_conditions
    # just accepts a username string and we call it directly. If the
    # function ever drops the escape, even a legit email containing
    # an apostrophe (e.g. o'brien@avientek.com) would break the SQL.
    hostile = "smoke.pwn'); DROP TABLE `tabUser`; --@avientek.test"
    sql = pp.get_permission_query_conditions(user=hostile)
    if sql is None:
        _fail("hostile-username caller must be scoped, got None")
    if frappe.db.escape(hostile) not in sql:
        _fail(
            f"escaped username not present verbatim: {sql}. "
            "frappe.db.escape() must be the sole interpolation path."
        )
    # frappe.db.escape() wraps and escapes; the raw DROP TABLE should
    # appear INSIDE the quoted string, never as parseable SQL.
    escaped = frappe.db.escape(hostile)
    if "DROP TABLE" in sql and "DROP TABLE" not in escaped:
        _fail(f"DROP TABLE leaked outside the escaped literal: {sql}")
    _ok("username properly escaped via frappe.db.escape — no injection vector")


def _check_has_permission_matches_query():
    """has_permission must accept docs the query would surface and
    reject ones the query would filter out."""
    print()
    print("=== has_permission stays in lockstep with the SQL filter ===")
    pp = _import()

    # Owner case — any user always sees their own
    u_req = _ensure_user("smoke.req2@avientek.test", [])
    fake_doc_owner = frappe._dict(owner=u_req, company="Any", department=None,
                                  workflow_state="Draft")
    if not pp.has_permission(fake_doc_owner, user=u_req):
        _fail("owner of PRF must always have read access")
    _ok("owner: accepted")

    # Accounts User + company match
    u_au = _ensure_user("smoke.au.match@avientek.test", ["Accounts User"])
    _clear_user_permissions(u_au)
    _set_user_permission(u_au, "Company", "Avientek FZCO")
    try:
        fake_co_match = frappe._dict(
            owner="someone.else@avientek.test",
            company="Avientek FZCO",
            workflow_state="Draft",
            department=None,
        )
        fake_co_miss = frappe._dict(
            owner="someone.else@avientek.test",
            company="Avientek KSA",
            workflow_state="Draft",
            department=None,
        )
        fake_proc_queue = frappe._dict(
            owner="someone.else@avientek.test",
            company="Avientek KSA",
            workflow_state="Approved Level 2",
            department=None,
        )
        if not pp.has_permission(fake_co_match, user=u_au):
            _fail("Accounts User must see PRFs from permitted companies")
        if pp.has_permission(fake_co_miss, user=u_au):
            _fail("Accounts User must NOT see PRFs outside permitted companies")
        if not pp.has_permission(fake_proc_queue, user=u_au):
            _fail("Accounts User must see PRFs in payment processing queue")
    finally:
        _clear_user_permissions(u_au)
    _ok("Accounts User: company match / no-match / processing queue all correct")

    # Full-vis role — accepts every doc
    u_fm = _ensure_user("smoke.fm@avientek.test", ["Finance Manager"])
    fake_random = frappe._dict(
        owner="someone.else@avientek.test",
        company="Avientek Anywhere",
        workflow_state="Draft",
        department=None,
    )
    if not pp.has_permission(fake_random, user=u_fm):
        _fail("Finance Manager must accept any PRF")
    _ok("Finance Manager: accepts any PRF")


# ---------------- runner -------------------------------------------


def run():
    print("=" * 64)
    print("Avientek smoke: 2026-06-13 PRF role-based visibility")
    print("=" * 64)
    _check_hook_wired()
    _check_administrator_no_filter()
    _check_full_visibility_roles()
    _check_requestor_floor_only()
    _check_accounts_user_with_company_perm()
    _check_accounts_user_no_company_perm()
    _check_dept_head_with_dept_perm_and_subtree()
    _check_sql_injection_safe()
    _check_has_permission_matches_query()

    # Don't commit — keep the test fakes contained
    frappe.db.rollback()
    print()
    print("All smoke checks PASSED ✓")
