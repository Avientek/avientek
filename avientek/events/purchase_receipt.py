import frappe
from frappe import _


BLOCKED_WORKFLOW_STATES = (
    "Approved for Update",
    "Updated Doc for Approval",
    "Sent for Revision",
    "Pending Revise",
    "Revised – Pending Approval",
)


def validate_po_workflow_state(doc, method=None):
    """Block Purchase Receipt if any linked PO is mid-update in the workflow."""
    po_names = set()
    for item in doc.items:
        if item.purchase_order:
            po_names.add(item.purchase_order)

    if not po_names:
        return

    blocked = frappe.db.sql(
        """
        SELECT name, workflow_state
        FROM `tabPurchase Order`
        WHERE name IN ({})
          AND workflow_state IN ({})
        """.format(
            ", ".join(["%s"] * len(po_names)),
            ", ".join(["%s"] * len(BLOCKED_WORKFLOW_STATES)),
        ),
        list(po_names) + list(BLOCKED_WORKFLOW_STATES),
        as_dict=True,
    )

    if blocked:
        msgs = [
            _("{0} is in <b>{1}</b> state").format(r.name, r.workflow_state)
            for r in blocked
        ]
        frappe.throw(
            _("Cannot submit Purchase Receipt. The following Purchase Orders "
              "have not completed the update approval workflow:")
            + "<br>" + "<br>".join(msgs),
            title=_("Purchase Order Update Pending"),
        )
