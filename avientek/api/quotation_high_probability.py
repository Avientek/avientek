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
    "CS",
    "Sales support L2",
    "System Manager",
    "Administrator",
)
# Single-approver pattern (Rahul/Sridhar 2026-05-08, mirrors SO).
DEFAULT_APPROVAL_ROLE = "CS"
DEFAULT_CREATOR_ROLE = "Sales support L2"

# Back-compat aliases — old imports may still reference these. Both
# now resolve to the single approver. New code must call _settings_roles().
DEFAULT_L1_ROLE = DEFAULT_APPROVAL_ROLE
DEFAULT_L2_ROLE = DEFAULT_APPROVAL_ROLE

# Cache key — busted automatically when Avientek Settings is saved
# (frappe.cache invalidates cached_doc).
_SETTINGS_CACHE_KEY = "_avtk_quote_high_prob_roles"


def _settings_roles():
    """Read role config from Avientek Settings (single doctype). Cached
    in process memory; cache busts when the settings doc is saved
    (frappe.clear_cache fires that). Falls back to module defaults if
    any setting is blank.

    V3 (2026-05-08): single approver replaced L1/L2.
    V3.1 (Sammish 2026-05-13): multi-role tables `quote_approver_roles`
    and `quote_creator_roles` are now the source of truth — the legacy
    single Link fields (`quote_approval_role`,
    `quote_high_prob_creator_role`) remain as fallbacks if the tables
    are empty.
    V3.2 (Rahul/Sammish 2026-05-14): restored TRUE Level 1 → Level 2
    approval chain per the BRD. New `quote_l2_approver_roles` table
    on Avientek Settings holds the L2 approver pool. The returned
    dict now exposes:
      - approver_roles    → L1 approver pool (first stage)
      - l2_approver_roles → L2 approver pool (second stage)
      - approver_role     → first L1 role (back-compat scalar)
      - l1_role / l2_role → first L1 / L2 role (back-compat scalars)
      - creator_roles, restricted, whitelisted (unchanged)
    If `quote_l2_approver_roles` is empty, L2 falls back to the L1
    pool (so old single-stage configs keep working)."""
    cached = frappe.local.flags.get(_SETTINGS_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        s = frappe.get_cached_doc("Avientek Settings")
        approver_roles = tuple(
            r.role for r in (s.get("quote_approver_roles") or []) if r.role
        )
        if not approver_roles and s.get("quote_approval_role"):
            approver_roles = (s.get("quote_approval_role"),)
        if not approver_roles:
            approver_roles = (DEFAULT_APPROVAL_ROLE,)

        l2_approver_roles = tuple(
            r.role for r in (s.get("quote_l2_approver_roles") or []) if r.role
        )
        # L2 pool falls back to L1 pool when not explicitly configured —
        # this keeps the workflow operable on sites that haven't yet
        # configured the L2 table (single-stage behaviour preserved).
        if not l2_approver_roles:
            l2_approver_roles = approver_roles

        creator_roles = tuple(
            r.role for r in (s.get("quote_creator_roles") or []) if r.role
        )
        if not creator_roles and s.get("quote_high_prob_creator_role"):
            creator_roles = (s.get("quote_high_prob_creator_role"),)
        if not creator_roles:
            creator_roles = (DEFAULT_CREATOR_ROLE,)

        restricted = tuple(
            r.role for r in (s.get("quote_high_prob_restricted_roles") or [])
            if r.role
        ) or DEFAULT_RESTRICTED_ROLES
    except Exception:
        approver_roles = (DEFAULT_APPROVAL_ROLE,)
        l2_approver_roles = approver_roles
        creator_roles = (DEFAULT_CREATOR_ROLE,)
        restricted = DEFAULT_RESTRICTED_ROLES

    # Whitelist = L1 + L2 approvers + creators + System Manager + Administrator.
    whitelisted = tuple(
        set(approver_roles) | set(l2_approver_roles) | set(creator_roles)
        | {"System Manager", "Administrator"}
    )

    # Primary (first) role for any back-compat reader that wants a scalar.
    approver_primary = approver_roles[0]
    l2_primary = l2_approver_roles[0]
    creator_primary = creator_roles[0]

    cfg = {
        # New plural form — preferred for new code.
        "approver_roles": approver_roles,         # L1 pool
        "l2_approver_roles": l2_approver_roles,   # L2 pool (falls back to L1)
        "creator_roles": creator_roles,
        # Back-compat scalar form — point at first role of each pool.
        "approver_role": approver_primary,
        "l1_role": approver_primary,
        "l2_role": l2_primary,
        "creator_role": creator_primary,
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

    db_prob = _effective_probability(doc.name)
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
          "exactly 100. To Cancel / Amend / Resubmit, scroll down to "
          "the <b>Document Approval</b> section, tick "
          "<i>Request for Update</i> or <i>Cancellation Check</i>, "
          "fill the note, and Save — the approver will review.").format(
            HIGH_PROB_THRESHOLD,
        ),
        title=_("High-Probability Quote Locked"),
    )


def _effective_probability(doc_name):
    """Return the higher of `probability` (numeric) and `probabilities`
    (Data field '100%'). Rahul 2026-05-12: QN-LLC-26-00399 was 100%
    visible but `probability=0` in DB — the original guard read only
    the numeric field and let me.sales3 cancel an Approved + 100% quote
    without any approval. Defense-in-depth: read both, take the max.
    """
    row = frappe.db.get_value(
        "Quotation", doc_name, ["probability", "probabilities"], as_dict=True
    ) or {}
    num = _flt(row.get("probability"))
    data = _flt(str(row.get("probabilities") or "0").rstrip("%").strip())
    return max(num, data)


def before_cancel(doc, method=None):
    """Block direct Cancel on a high-probability Quotation.

    Cancellation now flows through the Document Approval section's
    `custom_cancellation_check` checkbox — the approver moves the
    workflow_state to "Cancellation Approved" → "Cancelled" which
    sets `frappe.flags[_CONTEXT_BYPASS_FLAG]` so this guard skips.
    """
    if _user_has_whitelist_role() or frappe.flags.get(_CONTEXT_BYPASS_FLAG):
        return
    db_prob = _effective_probability(doc.name)
    if db_prob >= HIGH_PROB_THRESHOLD:
        frappe.throw(
            _("Cancel is blocked: this Quotation has probability "
              "{0}% (>= {1}%). To request cancellation, open the "
              "Quotation, scroll to the <b>Document Approval</b> "
              "section, tick <i>Cancellation Check</i>, fill the "
              "Cancellation Reason, and Save. The approver will "
              "review and approve the cancellation.").format(
                int(db_prob), HIGH_PROB_THRESHOLD,
            ),
            title=_("Cancel Requires Approval"),
        )


def on_update_after_submit(doc, method=None):
    """Catch Resubmit / Amend-like updates on submitted Quotations.

    Frappe fires `on_update_after_submit` on any allow_on_submit field
    change AFTER docstatus=1.

    Sridhar BRD correction 2026-05-07: For Quotations with current
    `db.probability < 75`, allow inline updates to the probability
    field WITHOUT Cancel + Amend. Other field changes still require
    the Cancel + Amend audit trail. (probability gets allow_on_submit=1
    via Property Setter; this validator polices what may go through.)

    Above-threshold rule (Rahul/Sridhar 2026-05-08): high-prob quotes
    only permit the whitelist 75->100 bump inline; any other change
    requires the user to tick "Request for Update" or
    "Cancellation Check" in the Document Approval section, fill the
    note, save, and route through the V3 approval workflow.
    """
    if _user_has_whitelist_role() or frappe.flags.get(_CONTEXT_BYPASS_FLAG):
        return
    db_prob = _effective_probability(doc.name)

    if db_prob < HIGH_PROB_THRESHOLD:
        # Inline probability edit is the only allow_on_submit path.
        if not _changed_fields(doc, exclude={"probability"}):
            return
        frappe.throw(
            _("Submitted Quotation: only the Probability field can be "
              "updated inline. To change other fields, use Cancel + "
              "Amend."),
            title=_("Edit Restricted"),
        )
        return

    # Permit the whitelist 75->100 bump even after submit.
    new_prob = _flt(doc.probability)
    if new_prob == 100 and not _changed_fields(doc, exclude={"probability"}):
        return

    # Permit the Document Approval transitions: when the user ticks
    # custom_request_for_update or custom_cancellation_check (with the
    # corresponding note) and the workflow_state is moving to one of
    # the V3 staging states, allow the save. The workflow itself
    # gates who can approve next.
    if doc.get("custom_request_for_update") or doc.get("custom_cancellation_check"):
        return

    # Permit edits when workflow_state is `Approved for Update` or
    # `Sent for Revision` — the approver has already opened editing.
    ws = (doc.get("workflow_state") or "").strip()
    if ws in ("Approved for Update", "Sent for Revision"):
        return

    # Special prices carve-out (Rahul 2026-05-08): updates to special
    # prices on Quotation Items are exempt from the high-prob lock
    # because they're discount adjustments rather than substantive
    # quote changes. If the only changes on this save are to special
    # price fields on the items table, allow it through.
    if _changed_only_special_prices(doc):
        return

    frappe.throw(
        _("Resubmit / Amend is blocked: this Quotation has "
          "probability {0}% (>= {1}%). To change anything other than "
          "probability, scroll to the <b>Document Approval</b> section, "
          "tick <i>Request for Update</i>, fill the note, and Save — "
          "the approver will review.").format(
            int(db_prob), HIGH_PROB_THRESHOLD,
        ),
        title=_("Action Requires Approval"),
    )


# ─────────────────────────────────────────────────────────────────────
# Notification — fires when probability transitions to 100%
# (Rahul/Sridhar 2026-05-08 — meeting record + WhatsApp).
# ─────────────────────────────────────────────────────────────────────


def notify_probability_100(doc, method=None):
    """Send an email + system notification when a Quotation's
    probability transitions to 100% on a submitted doc.

    Recipients:
      - Quote owner (creator)
      - Each Sales Person on the doc.sales_team child table (resolved
        to the user email mapped to the Sales Person record)
      - The configured `quote_approval_role` users (so the team that
        downstream-approves knows the quote is now fully committed)

    Idempotent: only fires when previous DB value < 100 and current
    value == 100. Subsequent saves at 100 don't re-fire."""
    if frappe.flags.get(_CONTEXT_BYPASS_FLAG):
        return
    try:
        new_prob = _flt(doc.probability)
        if new_prob != 100:
            return
        db_prob = _flt(frappe.db.get_value("Quotation", doc.name, "probability"))
        # If DB also reads 100 already, this save isn't a transition.
        # Check the doc.get_db_value if available; otherwise compare
        # Document.flags.in_insert, etc.
        # Simplest — compare with the pre-save value Frappe stored on
        # `doc._doc_before_save` (set by Frappe before validate hooks
        # fire when in_update=True).
        before = getattr(doc, "_doc_before_save", None)
        prev_prob = _flt(before.probability) if before else db_prob
        if prev_prob == 100:
            return  # already at 100; not a transition

        recipients = _resolve_prob_100_recipients(doc)
        if not recipients:
            return

        subject = _("Quotation {0} reached 100% probability").format(doc.name)
        message = (
            f"<p>Quotation <a href='/app/quotation/{doc.name}'>{doc.name}</a> "
            f"has been confirmed at <b>100% probability</b>.</p>"
            f"<ul>"
            f"<li>Customer: {(doc.party_name or doc.quotation_to or '—')}</li>"
            f"<li>Grand Total: {(doc.grand_total or 0):,.2f} {(doc.currency or '')}</li>"
            f"<li>Owner: {doc.owner}</li>"
            f"<li>Valid Till: {(doc.valid_till or '—')}</li>"
            f"</ul>"
            f"<p>This quote is now visible to downstream teams "
            f"(Procurement / Dispatch) for fulfillment.</p>"
        )
        frappe.sendmail(
            recipients=list(set(recipients)),
            subject=subject,
            message=message,
            reference_doctype="Quotation",
            reference_name=doc.name,
            now=False,
        )
    except Exception:
        # Never block the save on a notification failure.
        frappe.log_error(
            title="notify_probability_100 failed",
            message=frappe.get_traceback(),
        )


def _resolve_prob_100_recipients(doc):
    """Build the recipient list for the prob=100 notification. Reads
    dynamically — recipients change as soon as Avientek Settings
    approver roles or doc.sales_team change."""
    emails = []
    if doc.owner:
        emails.append(doc.owner)
    # Sales team
    for row in (doc.get("sales_team") or []):
        sp_name = getattr(row, "sales_person", None)
        if not sp_name:
            continue
        # Sales Person → User email (or contact_no if email blank)
        user_email = frappe.db.get_value("Sales Person", sp_name, "email_address")
        if user_email:
            emails.append(user_email)
    # Approver role users — any of the configured approver roles.
    cfg = _settings_roles()
    approver_roles = cfg.get("approver_roles") or ((cfg.get("approver_role"),) if cfg.get("approver_role") else ())
    if approver_roles:
        users = frappe.db.sql(
            """SELECT DISTINCT u.name
               FROM `tabUser` u
               INNER JOIN `tabHas Role` hr
                 ON hr.parent = u.name AND hr.parenttype = 'User'
               WHERE u.enabled = 1 AND u.email IS NOT NULL
                 AND hr.role IN %(roles)s""",
            {"roles": tuple(approver_roles)},
        )
        emails.extend([u[0] for u in users])
    # Filter out empty + Administrator (not a real inbox)
    return [e for e in emails if e and e.lower() not in ("administrator",)]


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


SPECIAL_PRICE_FIELDS = {
    "custom_special_price",
    "custom_special_rate",
    "custom_special_price_note",
    "custom_addl_discount_amount",
}


def _changed_only_special_prices(doc):
    """Return True if the only changes on this save are to fields in
    SPECIAL_PRICE_FIELDS on rows of `doc.items` (no top-level Quotation
    fields changed except those that recalculate from item rate, no
    other items-table fields changed). Used to grant the special-price
    carve-out on locked submitted quotes (Rahul 2026-05-08).

    Compares `doc.items` against the saved DB rows by row name. If a
    row was added, removed, or had any non-special-price field changed,
    returns False — the save needs the full Document Approval flow.
    """
    if not doc or not doc.get("name"):
        return False
    new_rows = doc.get("items") or []
    db_rows = frappe.db.sql(
        """SELECT name, item_code, qty, rate, amount,
                  custom_special_price, custom_special_rate,
                  custom_special_price_note, custom_addl_discount_amount
           FROM `tabQuotation Item`
           WHERE parent = %s AND parentfield = 'items'""",
        (doc.name,),
        as_dict=True,
    )
    db_by_name = {r["name"]: r for r in db_rows}

    # Row count must match (no add/remove)
    if len({r.get("name") for r in new_rows if r.get("name")}) != len(db_by_name):
        return False

    # Collect fields that should be unchanged (everything outside special-price set)
    SCALAR_GUARD = {"item_code", "qty", "rate", "amount"}

    saw_change = False
    for row in new_rows:
        rn = row.get("name")
        if not rn or rn not in db_by_name:
            return False  # new row added or unknown row
        db_row = db_by_name[rn]
        # Reject if any guarded field changed
        for fn in SCALAR_GUARD:
            if str(row.get(fn) or "") != str(db_row.get(fn) or ""):
                return False
        # See if any special-price field actually changed
        for fn in SPECIAL_PRICE_FIELDS:
            if str(row.get(fn) or "") != str(db_row.get(fn) or ""):
                saw_change = True

    if not saw_change:
        return False  # no special-price change either; let other checks decide

    # Also ensure no top-level Quotation field changed (except probability,
    # which is handled by other branches in on_update_after_submit).
    if _changed_fields(doc, exclude={"probability"}):
        return False

    return True


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
