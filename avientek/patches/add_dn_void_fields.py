"""Add Custom Fields on Delivery Note for the "Void Draft" workflow.

Jithin Avientek 2026-06-19: users frequently create duplicate Draft
Delivery Notes when stock is insufficient. Frappe's docstatus model
won't let them be cancelled (cancel only works on submitted docs),
so they currently delete — which breaks the DN naming series and
leaves audit gaps.

Solution: a "void" flag that marks the Draft as cancelled-in-spirit
without touching docstatus. The DN stays in the DB with its original
name (DN-FZCO-26-00715 still exists), list views show a red
"Cancelled" indicator, the items table goes read-only, and the
naming series stays continuous.

Fields added (all under section break "Void"):
  - custom_is_void (Check, hidden=0, no_copy=1, default=0)
      The flag itself. Once set, the doc is treated as cancelled in
      Avientek's UI and reports.
  - custom_void_reason (Small Text, depends_on=eval:doc.custom_is_void)
      Why was this Draft voided (required if voided). Captured for
      audit.
  - custom_voided_on (Datetime, read_only=1, no_copy=1)
      Timestamp set server-side by before_save hook when
      custom_is_void transitions 0 → 1.
  - custom_voided_by (Link User, read_only=1, no_copy=1)
      User who voided it. Set server-side same time as
      custom_voided_on.

All four fields go into a new section break "void_section" at the
end of the DN form. Idempotent — only inserts if the Custom Field
doesn't already exist.
"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


_FIELDS = [
    {
        "fieldname": "void_section",
        "label": "Void",
        "fieldtype": "Section Break",
        "collapsible": 1,
        "collapsible_depends_on": "eval:!doc.custom_is_void",
        "insert_after": "amended_from",
    },
    {
        "fieldname": "custom_is_void",
        "label": "Voided",
        "fieldtype": "Check",
        "default": 0,
        "no_copy": 1,
        "in_list_view": 0,
        "in_standard_filter": 1,
        "description": (
            "Mark this Draft as voided (cancelled-in-spirit). The "
            "DN stays in the DB with its original number — no "
            "naming-series gap. Avientek's UI treats voided drafts "
            "as Cancelled."
        ),
        "depends_on": "eval:doc.docstatus===0",
        "insert_after": "void_section",
    },
    {
        "fieldname": "custom_void_reason",
        "label": "Void Reason",
        "fieldtype": "Small Text",
        "depends_on": "eval:doc.custom_is_void",
        "mandatory_depends_on": "eval:doc.custom_is_void",
        "no_copy": 1,
        "insert_after": "custom_is_void",
    },
    {
        "fieldname": "void_col_break",
        "fieldtype": "Column Break",
        "insert_after": "custom_void_reason",
    },
    {
        "fieldname": "custom_voided_on",
        "label": "Voided On",
        "fieldtype": "Datetime",
        "read_only": 1,
        "no_copy": 1,
        "depends_on": "eval:doc.custom_is_void",
        "insert_after": "void_col_break",
    },
    {
        "fieldname": "custom_voided_by",
        "label": "Voided By",
        "fieldtype": "Link",
        "options": "User",
        "read_only": 1,
        "no_copy": 1,
        "depends_on": "eval:doc.custom_is_void",
        "insert_after": "custom_voided_on",
    },
]


def execute():
    print("[add_dn_void_fields] adding Void fields to Delivery Note…")
    create_custom_fields({"Delivery Note": _FIELDS}, ignore_validate=True)
    print(f"[add_dn_void_fields] done — {len(_FIELDS)} fields ensured")
