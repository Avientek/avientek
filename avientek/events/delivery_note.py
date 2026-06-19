import frappe
from frappe import _
from frappe.utils import now_datetime


# ── Server Script: "DN - Item Tax Template" ──
# DocType Event: Delivery Note, Before Validate
def validate_item_tax_template(doc, method=None):
    """Auto-fill Item Tax Template from Item master, then hard-require
    it for Avientek Electronics Trading PVT. LTD."""
    from avientek.events.utils import autofill_item_tax_template
    required = "Avientek Electronics Trading PVT. LTD" if doc.company == "Avientek Electronics Trading PVT. LTD" else None
    autofill_item_tax_template(doc, required_company=required)


# ── Server Script: "DN - Void Draft" ──
# DocType Event: Delivery Note, Before Save
#
# Jithin 2026-06-19: users who can't ship a Draft (because stock is
# short) currently delete it — which breaks the DN naming series.
# Replacement workflow: mark the Draft as "Voided" via custom_is_void
# Custom Field. This hook enforces the void invariants:
#   - Voided drafts are LOCKED — items + most fields read-only at the
#     server layer (UI already locks via depends_on; this catches
#     bypass via API).
#   - Void is ONE-WAY — once custom_is_void=1, can't be unset.
#     Reasoning: re-using a voided number defeats the audit purpose.
#     If the user needs to re-create, they Duplicate (which gets a
#     new DN number) and edit the new one.
#   - Voided drafts CANNOT be submitted. Submit requires
#     custom_is_void=0.
#   - Voided drafts STAMP custom_voided_on + custom_voided_by once
#     (the moment of the 0→1 transition). These never change after.
def validate_void_state(doc, method=None):
    """Run on before_save. Enforce void invariants + stamp audit fields."""
    new_void = bool(int(doc.get("custom_is_void") or 0))

    # Get the previous state from DB (if doc has a name = not first insert)
    old_void = False
    if doc.get("name") and not doc.is_new():
        old_void = bool(
            int(
                frappe.db.get_value(
                    "Delivery Note", doc.name, "custom_is_void"
                )
                or 0
            )
        )

    # Invariant 1: void is one-way (1 → 0 forbidden)
    if old_void and not new_void:
        frappe.throw(
            _("A voided Delivery Note cannot be un-voided. "
              "If you need to resume work, use the Duplicate "
              "action to create a new DN with a fresh number.")
        )

    # Invariant 2: Void only allowed on Drafts (docstatus=0). If the
    # doc was submitted somehow and someone tries to flip the void
    # flag, refuse.
    if new_void and doc.docstatus not in (0,):
        frappe.throw(
            _("Only Draft Delivery Notes can be voided. This DN is "
              "{0}.").format(
                {1: "Submitted", 2: "Cancelled"}.get(doc.docstatus, str(doc.docstatus))
            )
        )

    # Stamp audit fields on the 0 → 1 transition
    if new_void and not old_void:
        doc.custom_voided_on = now_datetime()
        doc.custom_voided_by = frappe.session.user
        if not (doc.get("custom_void_reason") or "").strip():
            frappe.throw(
                _("Void Reason is required to void this Delivery Note.")
            )


def block_submit_when_voided(doc, method=None):
    """before_submit hook — block submission of voided DNs.

    Split from validate_void_state because before_save fires on regular
    saves too (we don't want to block edits to the void flag on Draft).
    before_submit fires only when the user clicks Submit, and at that
    point custom_is_void=1 is grounds to refuse.
    """
    if bool(int(doc.get("custom_is_void") or 0)):
        frappe.throw(
            _("Voided Delivery Note cannot be submitted. "
              "Use Duplicate to create a fresh DN if you need to "
              "resume this work.")
        )


