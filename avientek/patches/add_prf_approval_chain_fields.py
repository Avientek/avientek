"""Add Custom Fields on Payment Request Form for the configurable Approval Rule engine.

Phase 1 of the PRF authorization scalable-rewrite (2026-06-19, Jithin ask).

Three Custom Fields, all read-only — set by the resolver at before_save:
  - custom_approval_rule          Link to the matched PRF Approval Rule
  - custom_approval_chain         Long Text (JSON) — the resolved approver chain
  - custom_current_approval_level Int — which level is awaiting sign-off now

The resolver lives at avientek.events.payment_request_form.resolve_approval_chain
(Phase 2 — separate commit). This patch only ships the schema so the resolver
has somewhere to write.

Idempotent — re-running migrate is a no-op if the fields already exist.
"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


_FIELDS = [
    {
        "fieldname": "custom_approval_chain_section",
        "label": "Approval Chain (resolved)",
        "fieldtype": "Section Break",
        "collapsible": 1,
        "insert_after": "is_tr_lc_payment",
        "description": (
            "Auto-resolved at save by avientek.events.payment_request_form."
            "resolve_approval_chain. Read-only — configure via PRF Approval Rule masters."
        ),
    },
    {
        "fieldname": "custom_approval_rule",
        "label": "Matched Approval Rule",
        "fieldtype": "Link",
        "options": "PRF Approval Rule",
        "read_only": 1,
        "no_copy": 1,
        "insert_after": "custom_approval_chain_section",
    },
    {
        "fieldname": "custom_current_approval_level",
        "label": "Current Approval Level",
        "fieldtype": "Int",
        "read_only": 1,
        "no_copy": 1,
        "default": 0,
        "insert_after": "custom_approval_rule",
        "description": "0 = not yet routed / no rule matched. 1+ = awaiting sign-off at that level.",
    },
    {
        "fieldname": "custom_approval_chain_col_break",
        "fieldtype": "Column Break",
        "insert_after": "custom_current_approval_level",
    },
    {
        "fieldname": "custom_approval_chain",
        "label": "Approval Chain (JSON)",
        "fieldtype": "Long Text",
        "read_only": 1,
        "no_copy": 1,
        "insert_after": "custom_approval_chain_col_break",
        "description": (
            "JSON array of resolved approvers per level. Shape: "
            "[{\"level\": 1, \"user\": \"x@y.com\", \"signed_on\": null}, ...]. "
            "Populated by the resolver; consumed by workflow transition conditions."
        ),
    },
]


def execute():
    print("[add_prf_approval_chain_fields] adding resolved-chain fields to Payment Request Form")
    create_custom_fields({"Payment Request Form": _FIELDS}, ignore_validate=True)
    print(f"[add_prf_approval_chain_fields] done — {len(_FIELDS)} fields ensured")
