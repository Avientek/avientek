import frappe
from frappe import _


# ── Server Script: "PR Validate supplier company" ──
# DocType Event: Purchase Receipt, Before Validate
def validate_supplier_company(doc, method=None):
    """Ensure supplier belongs to the same company on the receipt."""
    if doc.supplier and doc.company and not doc.is_internal_supplier:
        supplier = frappe.get_doc("Supplier", doc.supplier)
        if supplier.company and supplier.company != doc.company:
            frappe.throw(_("Supplier does not belongs to company"))


# ── Server Script: "PR - Item Tax Template" ──
# DocType Event: Purchase Receipt, Before Validate
def validate_item_tax_template(doc, method=None):
    """Require Item Tax Template for all items when company is Avientek Electronics Trading PVT. LTD."""
    if doc.company == "Avientek Electronics Trading PVT. LTD":
        for item in doc.items:
            if not item.item_tax_template:
                frappe.throw(
                    _("Kindly choose Item Tax template for item: {0} in Row# {1}").format(
                        item.item_code, item.idx
                    )
                )


# ── Server Script: "Pull Bundles from DO" (DISABLED) ──
# DocType Event: Purchase Receipt, Before Submit
# NOTE: This script was disabled in the site. Same logic as PR - Item Tax Template.
# def validate_item_tax_template_before_submit(doc, method=None):
#     if doc.company == "Avientek Electronics Trading PVT. LTD":
#         for item in doc.items:
#             if not item.item_tax_template:
#                 frappe.throw(
#                     _("Kindly choose Item Tax template for item: {0} in Row# {1}").format(
#                         item.item_code, item.idx
#                     )
#                 )


# ── Server Script: "ADD BATCH BUNDLE PR" ──
# DocType Event: Purchase Receipt, Before Submit
def add_batch_bundle_from_intercompany_dn(doc, method=None):
    """For inter-company transfers, create Serial and Batch Bundles from linked Delivery Note."""
    if not doc.custom_inter_company_do:
        return

    dn_name = doc.custom_inter_company_do
    if not frappe.db.exists("Delivery Note", dn_name):
        frappe.throw(_("Linked Delivery Note '{0}' invalid.").format(dn_name))

    dn_doc = frappe.get_doc("Delivery Note", dn_name)

    # Map DN items by (item_code, qty) for matching
    dn_items_map = {}
    for d_item in dn_doc.items:
        key = (d_item.item_code, float(d_item.qty))
        if key not in dn_items_map:
            dn_items_map[key] = []
        dn_items_map[key].append(d_item)

    mismatch_messages = []
    creation_plan = []

    # Match PR items with DN items
    for pr_item in doc.items:
        key = (pr_item.item_code, float(pr_item.qty))
        if key not in dn_items_map or not dn_items_map[key]:
            mismatch_messages.append(
                _("Row #{0}: No matching DN item for {1}, Qty {2}.").format(
                    pr_item.idx, pr_item.item_code, pr_item.qty
                )
            )
            continue

        dn_item = dn_items_map[key].pop(0)
        pr_item.delivery_note_item = dn_item.name

        dn_bundle_name = dn_item.serial_and_batch_bundle
        dn_batch_no = dn_item.batch_no

        if not dn_bundle_name and not dn_batch_no:
            continue

        creation_plan.append({
            "pr_item": pr_item,
            "dn_bundle_name": dn_bundle_name,
            "dn_batch_no": dn_batch_no,
            "dn_item": dn_item,
        })

    if mismatch_messages:
        frappe.throw(_("Mismatch found:") + "\n" + "\n".join(mismatch_messages))

    # STEP 1: Pre-create batches with correct manufacturing dates
    for row in creation_plan:
        dn_bundle_name = row["dn_bundle_name"]
        dn_batch_no = row["dn_batch_no"]
        pr_item = row["pr_item"]

        if dn_bundle_name:
            existing_dn_bundle = frappe.get_doc("Serial and Batch Bundle", dn_bundle_name)
            for entry_line in existing_dn_bundle.entries:
                batch_no = entry_line.batch_no
                if not batch_no:
                    continue
                if not frappe.db.exists("Batch", batch_no):
                    _create_batch_from_source(batch_no, pr_item.item_code, batch_no)
        elif dn_batch_no:
            if not frappe.db.exists("Batch", dn_batch_no):
                _create_batch_from_source(dn_batch_no, pr_item.item_code, dn_batch_no)

    # STEP 2: Create bundles (batches now exist with correct dates)
    for row in creation_plan:
        pr_item = row["pr_item"]
        dn_bundle_name = row["dn_bundle_name"]
        dn_batch_no = row["dn_batch_no"]

        new_bundle_doc = frappe.new_doc("Serial and Batch Bundle")
        new_bundle_doc.naming_series = "SABB-.########"
        new_bundle_doc.company = doc.company
        new_bundle_doc.item_code = pr_item.item_code
        new_bundle_doc.warehouse = pr_item.warehouse
        new_bundle_doc.type_of_transaction = "Inward"
        new_bundle_doc.voucher_type = "Purchase Receipt"
        new_bundle_doc.voucher_no = doc.name
        new_bundle_doc.voucher_detail_no = pr_item.name
        new_bundle_doc.posting_date = doc.posting_date
        new_bundle_doc.posting_time = doc.posting_time

        if dn_bundle_name:
            existing_dn_bundle = frappe.get_doc("Serial and Batch Bundle", dn_bundle_name)
            for entry_line in existing_dn_bundle.entries:
                new_bundle_doc.append("entries", {
                    "batch_no": entry_line.batch_no,
                    "qty": abs(float(entry_line.qty)),
                    "incoming_rate": float(pr_item.rate or 0),
                    "warehouse": pr_item.warehouse,
                })
        else:
            new_bundle_doc.append("entries", {
                "batch_no": dn_batch_no,
                "qty": float(pr_item.qty),
                "incoming_rate": float(pr_item.rate or 0),
                "warehouse": pr_item.warehouse,
            })

        new_bundle_doc.insert(ignore_permissions=True)
        pr_item.serial_and_batch_bundle = new_bundle_doc.name

        if not dn_bundle_name and dn_batch_no:
            pr_item.batch_no = dn_batch_no


def _create_batch_from_source(batch_no, item_code, source_batch_no):
    """Helper: create a new Batch copying dates from source batch."""
    dn_batch_doc = frappe.get_doc("Batch", source_batch_no)
    new_batch = frappe.new_doc("Batch")
    new_batch.batch_id = batch_no
    new_batch.item = item_code
    new_batch.manufacturing_date = dn_batch_doc.manufacturing_date
    new_batch.expiry_date = dn_batch_doc.expiry_date
    if dn_batch_doc.supplier:
        new_batch.supplier = dn_batch_doc.supplier
    if dn_batch_doc.description:
        new_batch.description = dn_batch_doc.description
    new_batch.insert(ignore_permissions=True)
    frappe.msgprint(
        _("Created Batch {0} with manufacturing date {1}").format(
            batch_no, dn_batch_doc.manufacturing_date
        ),
        alert=True,
    )


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
