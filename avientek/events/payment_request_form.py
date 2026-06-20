"""Event hooks for Payment Request Form.

Phase 2 of the configurable PRF authorization rewrite (2026-06-19, Jithin).
Schema landed in Phase 1 (ed4d7e3); this module ships the resolver that
populates the new fields.

Hook wiring (see hooks.py):
    Payment Request Form -> before_save -> resolve_approval_chain

The resolver:
  1. Pulls active rules (is_active=1, valid_from/to in range).
  2. Sorts by priority asc, then creation asc.
  3. For each rule, evaluates conditions against the PRF (AND of all).
  4. First match wins — stamps custom_approval_rule + custom_approval_chain.
  5. If NO rule matches, leaves the fields blank — existing role-based
     workflow continues to gate the PRF. Zero breakage by design.

Amount canon: always company currency, read from total_outstanding_amount.
"""
import json
import frappe
from frappe import _
from frappe.utils import getdate, flt


# ── Public hook ──
def resolve_approval_chain(doc, method=None):
    """before_save hook — match PRF against active PRF Approval Rules and
    stamp the resolved chain. Idempotent."""
    rule = _find_matching_rule(doc)
    if not rule:
        doc.custom_approval_rule = None
        doc.custom_approval_chain = None
        doc.custom_current_approval_level = 0
        return

    chain = _build_chain(rule, doc)
    if not chain:
        doc.custom_approval_rule = None
        doc.custom_approval_chain = None
        doc.custom_current_approval_level = 0
        return

    doc.custom_approval_rule = rule.name
    doc.custom_approval_chain = json.dumps(chain, default=str)
    doc.custom_current_approval_level = _first_unsigned_level(chain)


# ── Whitelisted preview for the rule's "Test against a PRF" button ──
@frappe.whitelist()
def preview_resolved_chain(prf_name):
    doc = frappe.get_doc("Payment Request Form", prf_name)
    rule = _find_matching_rule(doc)
    if not rule:
        return {"matched_rule": None, "chain": [], "reason": "No active rule matched."}
    chain = _build_chain(rule, doc)
    return {
        "matched_rule": rule.name,
        "rule_name": rule.rule_name,
        "priority": rule.priority,
        "chain": chain,
        "current_level": _first_unsigned_level(chain),
        "prf_amount": flt(doc.get("total_outstanding_amount") or 0),
        "prf_company": doc.get("company"),
        "prf_payment_type": doc.get("payment_type"),
        "prf_party_type": doc.get("party_type"),
        "prf_owner": doc.get("owner"),
    }


# ── Rule matching ──
def _find_matching_rule(doc):
    """Returns the highest-priority active rule that matches the PRF, or None."""
    today = getdate()
    rules = frappe.get_all(
        "PRF Approval Rule",
        filters={"is_active": 1},
        fields=["name"],
        order_by="priority asc, creation asc",
    )
    for r in rules:
        rule = frappe.get_doc("PRF Approval Rule", r.name)
        if _rule_matches(rule, doc, today):
            return rule
    return None


def _rule_matches(rule, doc, today):
    # Date band
    if rule.valid_from and today < getdate(rule.valid_from):
        return False
    if rule.valid_to and today > getdate(rule.valid_to):
        return False

    # Company
    if rule.company and rule.company != doc.get("company"):
        return False

    # Payment type
    if rule.payment_type and rule.payment_type != doc.get("payment_type"):
        return False

    # Party type
    if rule.party_type and rule.party_type != doc.get("party_type"):
        return False

    # Requesting department — resolve PRF owner -> Employee.department,
    # then walk up parent_department to handle sub-departments.
    if rule.requesting_department:
        owner_dept = _resolve_owner_department(doc)
        if not owner_dept:
            return False
        if not _is_descendant_of(owner_dept, rule.requesting_department):
            return False

    # Amount band — always in company currency (total_outstanding_amount)
    amt = flt(doc.get("total_outstanding_amount") or 0)
    if rule.amount_from and amt < flt(rule.amount_from):
        return False
    if rule.amount_to and amt > flt(rule.amount_to):
        return False

    return True


# ── Chain building ──
def _build_chain(rule, doc):
    """Build the JSON chain from the rule's approval_chain child rows.
    Skips:
      - Levels whose min_amount_for_level > PRF amount (tiered within rule)
      - Self-approval (requester == approver) — auto-skip that level
    """
    amt = flt(doc.get("total_outstanding_amount") or 0)
    requester = doc.get("owner")
    out = []
    for row in sorted(rule.approval_chain, key=lambda r: int(r.level or 0)):
        min_amt = flt(row.min_amount_for_level or 0)
        if min_amt and amt < min_amt:
            continue

        if row.approver_type == "User":
            if row.approver_user == requester:
                continue  # self-approval skip
            out.append(
                {
                    "level": int(row.level),
                    "type": "User",
                    "user": row.approver_user,
                    "signed_on": None,
                    "signed_by": None,
                }
            )
        elif row.approver_type == "Role":
            out.append(
                {
                    "level": int(row.level),
                    "type": "Role",
                    "role": row.approver_role,
                    "signed_on": None,
                    "signed_by": None,
                }
            )

    # Re-number levels 1..N (since some may have been skipped)
    for i, entry in enumerate(out, start=1):
        entry["level"] = i
    return out


def _first_unsigned_level(chain):
    for entry in chain:
        if not entry.get("signed_on"):
            return int(entry["level"])
    return 0  # fully signed


# ── Helpers ──
def _resolve_owner_department(doc):
    owner = doc.get("owner")
    if not owner:
        return None
    # Prefer Employee.department; fall back to User.department.
    dept = frappe.db.get_value("Employee", {"user_id": owner}, "department")
    if dept:
        return dept
    return frappe.db.get_value("User", owner, "department")


_DEPT_ANCESTRY_GUARD = 16  # cycle protection


def _is_descendant_of(dept, ancestor):
    """Walk parent_department chain from dept; return True if ancestor is on the path."""
    if dept == ancestor:
        return True
    seen = set()
    cur = dept
    depth = 0
    while cur and depth < _DEPT_ANCESTRY_GUARD:
        if cur in seen:
            return False
        seen.add(cur)
        parent = frappe.db.get_value("Department", cur, "parent_department")
        if parent == ancestor:
            return True
        cur = parent
        depth += 1
    return False
