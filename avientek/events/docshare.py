import frappe


# ── Server Script: "PO Auto Share with Write Access" ──
# DocType Event: DocShare, Before Insert
def auto_share_po_with_write(doc, method=None):
    """When a Purchase Order is shared, automatically grant write and submit access."""
    if doc.share_doctype == "Purchase Order":
        doc.write = 1
        doc.submit = 1
