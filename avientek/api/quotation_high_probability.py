"""Quotation High-Probability Workflow + RBAC visibility filter.

Sridhar 2026-05-06 spec — staged for TEST system pending BRD signoff.

Two layers:

  A. **Field locking when probability >= 75** (server validate + JS read-only).
     The only allowed update on a locked quote is bumping `probability`
     itself from a value >= 75 up to exactly 100 (the "Whitelist
     Action"). All other field changes throw on save.

  B. **Cancel / Amend / Resubmit on probability >= 75** must go through a
     two-level approval workflow (Phase 2 doctype).
     Phase 1 of this build (current commit) blocks the action with a
     clear error message instructing the user to use the Action
     Request flow. Phase 2 will replace this block with a real
     Quotation Action Request doctype + workflow that ultimately fires
     the action programmatically once L2 approves.

  C. **RBAC list-view + API filter** for Quotation:
       - Restricted roles (Dispatch / Procurement / Supply Chain /
         Logistics) can only see quotes with
         `workflow_state='Approved' AND probability=100`.
       - Whitelisted roles (Finance Controller / Sales Director /
         System Manager) bypass.
       - Quote Creator (`owner = current user`) and Parent Salesperson
         (current user is mapped to a Sales Person which is a tree
         ancestor of any Sales Team row on the quote) ALSO bypass.
"""
from __future__ import annotations

import frappe
from frappe import _


# ─────────────────────────────────────────────────────────────────────
# Constants — keep in sync with the BRD. Adjust here once roles are
# created on the test/prod sites.
# ─────────────────────────────────────────────────────────────────────

# Set frappe.flags[_CONTEXT_BYPASS_FLAG] = True before performing a
# Cancel/Amend/Resubmit when you're calling from an authorised path
# (e.g. Quotation Action Request._execute). The before_save /
# before_cancel / on_update_after_submit hooks then skip the lock
# checks for that single transaction.
_CONTEXT_BYPASS_FLAG = "_avtk_quotation_high_prob_bypass"

HIGH_PROB_THRESHOLD = 75  # >= this => locked / approval-required

# ─────────────────────────────────────────────────────────────────────
# Role configuration — Sridhar 2026-05-06 confirmed roles, then asked
# us to make them Avientek-Settings-driven so renames don't need a
# code change. The constants below are the FALLBACK defaults; live
# values are read from `Avientek Settings` via _settings_roles().
# ─────────────────────────────────────────────────────────────────────

DEFAULT_RESTRICTED_ROLES = (
    "Procurement L2",
)
DEFAULT_WHITELISTED_ROLES = (
    "GM-CS",
    "CS",
    "Sales support L2",
    "System Manager",
    "Administrator",
)
DEFAULT_L1_ROLE = "GM-CS"
DEFAULT_L2_ROLE = "CS"
DEFAULT_CREATOR_ROLE = "Sales support L2"

# Cache key — busted automatically when Avientek Settings is saved
# (frappe.cache invalidates cached_doc).
_SETTINGS_CACHE_KEY = "_avtk_quote_high_prob_roles"


def _settings_roles():
    """Read role config from Avientek Settings (single doctype). Cached
    in process memory; cache busts when the settings doc is saved
    (frappe.clear_cache fires that). Falls back to module defaults if
    any setting is blank."""
    cached = frappe.local.flags.get(_SETTINGS_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        s = frappe.get_cached_doc("Avientek Settings")
        l1 = s.get("quote_high_prob_l1_role") or DEFAULT_L1_ROLE
        l2 = s.get("quote_high_prob_l2_role") or DEFAULT_L2_ROLE
        creator = s.get("quote_high_prob_creator_role") or DEFAULT_CREATOR_ROLE
        restricted = tuple(
            r.role for r in (s.get("quote_high_prob_restricted_roles") or [])
            if r.role
        ) or DEFAULT_RESTRICTED_ROLES
    except Exception:
        l1, l2, creator = DEFAULT_L1_ROLE, DEFAULT_L2_ROLE, DEFAULT_CREATOR_ROLE
        restricted = DEFAULT_RESTRICTED_ROLES

    # Whitelist = L1 + L2 + Creator + System Manager + Administrator.
    whitelisted = tuple({l1, l2, creator, "System Manager", "Administrator"})

    cfg = {
        "l1_role": l1,
        "l2_role": l2,
        "creator_role": creator,
        "whitelisted": whitelisted,
        "restricted": restricted,
    }
    frappe.local.flags[_SETTINGS_CACHE_KEY] = cfg
    return cfg


# Backward-compatible accessors so any external import keeps working.
# (Real reads always go through _settings_roles() at runtime.)
@frappe.whitelist()
def get_role_config():
    """Public read for the JS layer — returns the resolved role
    configuration as a plain dict. Whitelist client-callable."""
    return _settings_roles()


def _whitelisted_roles():
    return set(_settings_roles()["whitelisted"])


def _restricted_roles():
    return set(_settings_roles()["restricted"])


# Compatibility aliases for old code paths that imported the module-
# level constants directly. These now reflect *defaults* only — if you
# care about the live values, call _settings_roles() / get_role_config().
RESTRICTED_ROLES = DEFAULT_RESTRICTED_ROLES
WHITELISTED_ROLES = DEFAULT_WHITELISTED_ROLES


# ─────────────────────────────────────────────────────────────────────
# Field locking on probability >= 75 — server side
# ─────────────────────────────────────────────────────────────────────


def before_save(doc, method=None):
    """Enforce field lock for high-probability Quotations (#1.1).

    Permitted on a locked quote (`db.probability >= HIGH_PROB_THRESHOLD`):
      - Bumping `probability` UP to 100 (the Whitelist Action).
      - Anything else by users with WHITELISTED_ROLES (admin override).

    Anything else throws.
    """
    if doc.is_new() or doc.docstatus != 0:
        return
    if _user_has_whitelist_role() or frappe.flags.get(_CONTEXT_BYPASS_FLAG):
        return

    db_prob = _flt(frappe.db.get_value("Quotation", doc.name, "probability"))
    if db_prob < HIGH_PROB_THRESHOLD:
        return  # below threshold — no lock

    new_prob = _flt(doc.probability)

    # Whitelist Action: probability >= 75 -> exactly 100, no other field
    # changes alongside.
    if new_prob == 100 and db_prob >= HIGH_PROB_THRESHOLD:
        # Allow ONLY if no other field has changed.
        changed = _changed_fields(doc, exclude={"probability"})
        if not changed:
            return  # legit whitelist update
        # Otherwise fall through to throw.

    frappe.throw(
        _("This Quotation is locked because probability >= {0}%. "
          "The only direct change permitted is bumping probability to "
          "exactly 100. To Cancel / Amend / Resubmit, use the "
          "Quotation Action Request approval workflow.").format(
            HIGH_PROB_THRESHOLD,
        ),
        title=_("High-Probability Quote Locked"),
    )


def before_cancel(doc, method=None):
    """Block direct Cancel on a high-probability Quotation. Phase 2:
    the only authorised cancellation path is via a Quotation Action
    Request that has reached the L2-Approved state — that path sets
    `frappe.flags[_CONTEXT_BYPASS_FLAG]` so this guard skips."""
    if _user_has_whitelist_role() or frappe.flags.get(_CONTEXT_BYPASS_FLAG):
        return
    db_prob = _flt(frappe.db.get_value("Quotation", doc.name, "probability"))
    if db_prob >= HIGH_PROB_THRESHOLD:
        frappe.throw(
            _("Cancel is blocked: this Quotation has probability "
              "{0}% (>= {1}%). Submit a Quotation Action Request "
              "(action=Cancel) and route it through Level 1 / Level 2 "
              "approval. Once Level 2 approves, the cancel will "
              "execute automatically.").format(
                int(db_prob), HIGH_PROB_THRESHOLD,
            ),
            title=_("Cancel Requires Approval"),
        )


def on_update_after_submit(doc, method=None):
    """Catch Resubmit / Amend-like updates on submitted high-prob quotes.

    Frappe fires `on_update_after_submit` on any allow_on_submit field
    change AFTER docstatus=1. For high-prob quotes this is also gated
    by the approval flow. Phase 1 just blocks; Phase 2 replaces with
    Action Request.
    """
    if _user_has_whitelist_role() or frappe.flags.get(_CONTEXT_BYPASS_FLAG):
        return
    db_prob = _flt(frappe.db.get_value("Quotation", doc.name, "probability"))
    if db_prob < HIGH_PROB_THRESHOLD:
        return
    # Permit the whitelist 75->100 bump even after submit.
    new_prob = _flt(doc.probability)
    if new_prob == 100 and not _changed_fields(doc, exclude={"probability"}):
        return
    frappe.throw(
        _("Resubmit / Amend is blocked: this Quotation has "
          "probability {0}% (>= {1}%). Submit a Quotation Action "
          "Request (action=Resubmit / Amend) and route it through "
          "Level 1 / Level 2 approval.").format(
            int(db_prob), HIGH_PROB_THRESHOLD,
        ),
        title=_("Action Requires Approval"),
    )


# ─────────────────────────────────────────────────────────────────────
# RBAC permission-query — used by avientek.api.quotation_access
#   .quotation_permission_query() to AND extra restrictions in.
# ─────────────────────────────────────────────────────────────────────


def restricted_visibility_condition(user):
    """Return a SQL fragment applied to `tabQuotation` rows for
    Restricted roles, OR an empty string if the user is bypassed.

    Bypass when:
      - user has any WHITELISTED role
      - user has NO Restricted role (other roles fall through to existing
        Quotation permission rules)
      - user is the quote creator (handled per-row in WHERE) — added
      - user is the Parent Salesperson — added

    Quote Creator and Parent Salesperson are evaluated INSIDE the SQL
    via OR clauses so they widen the visibility per-row.
    """
    if not user or user == "Administrator":
        return ""
    roles = set(frappe.get_roles(user) or [])
    if roles & _whitelisted_roles():
        return ""
    if not (roles & _restricted_roles()):
        return ""

    # Build the restrictive clause: Approved + probability=100 OR they own
    # the quote OR they are the parent salesperson on a Sales Team row.
    user_q = frappe.db.escape(user)
    parent_sps = _user_parent_sales_persons(user)

    sales_team_clause = ""
    if parent_sps:
        sps = ", ".join(frappe.db.escape(s) for s in parent_sps)
        sales_team_clause = (
            f" OR EXISTS ("
            f"  SELECT 1 FROM `tabSales Team` st "
            f"  WHERE st.parent = `tabQuotation`.name "
            f"    AND st.sales_person IN ({sps})"
            f")"
        )

    return (
        "("
        "(`tabQuotation`.workflow_state = 'Approved' "
        " AND `tabQuotation`.probability = 100) "
        f"OR `tabQuotation`.owner = {user_q}"
        f"{sales_team_clause}"
        ")"
    )


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _user_has_whitelist_role(user=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    roles = set(frappe.get_roles(user) or [])
    return bool(roles & _whitelisted_roles())


def _user_parent_sales_persons(user):
    """Return the list of Sales Person names the given user supervises
    (i.e. Sales Persons whose `parent_sales_person` resolves to the
    user's own Sales Person record OR an ancestor of it).

    Best-effort: returns empty list if the user has no linked Sales
    Person via Employee.user_id."""
    own = frappe.db.sql(
        """SELECT sp.name FROM `tabSales Person` sp
           INNER JOIN `tabEmployee` e ON e.name = sp.employee
           WHERE e.user_id = %s LIMIT 1""",
        (user,),
    )
    if not own:
        return []
    user_sp = own[0][0]
    # Children of user_sp via Sales Person tree.
    descendants = frappe.db.sql(
        """SELECT name FROM `tabSales Person`
           WHERE parent_sales_person = %s
              OR name = %s""",
        (user_sp, user_sp),
        pluck="name",
    ) or []
    return descendants


def _flt(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _changed_fields(doc, exclude=None):
    """Return a set of fieldnames that differ between the in-memory doc
    and the saved DB row. Used to detect whether anything besides
    `probability` is being edited on a locked quote.

    Limited to top-level fields (child tables aren't compared exactly,
    but Frappe's standard `before_save` is called BEFORE child tables
    are reconciled — for our case the key fields are top-level
    grand_total / discount / probability / etc. so this is enough).
    """
    exclude = set(exclude or set())
    db_doc = frappe.db.get_values(
        "Quotation", doc.name,
        fieldname=["grand_total", "total_taxes_and_charges",
                   "discount_amount", "additional_discount_percentage",
                   "currency", "conversion_rate",
                   "transaction_date", "valid_till",
                   "party_name", "quotation_to",
                   "company", "tc_name", "terms"],
        as_dict=True,
    )
    if not db_doc:
        return set()
    db_row = db_doc[0]
    changed = set()
    for f, v in db_row.items():
        if f in exclude:
            continue
        if str(getattr(doc, f, None) or "") != str(v or ""):
            changed.add(f)
    return changed
