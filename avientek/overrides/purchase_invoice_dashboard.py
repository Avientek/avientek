"""Override the Purchase Invoice Connections panel to fix the Landed Cost
Voucher count.

Jithin 2026-05-21 (PINV-FZCO-26-00520): the standard ERPNext PI
dashboard at apps/erpnext/.../purchase_invoice_dashboard.py declares:

    "non_standard_fieldnames": {
        "Landed Cost Voucher": "receipt_document",
    }

The Connections counter at apps/frappe/.../desk/notifications.py
`get_external_links` interprets that as
`frappe.get_all("Landed Cost Voucher", filters={"receipt_document": <pi>})`
— but `receipt_document` is on the CHILD doctype `Landed Cost Purchase
Receipt`, not the parent. The parent table has no such column, so the
query silently returns 0 and the "Landed Cost Voucher" pill shows zero
even when LCVs exist linked through the child table.

The fix is to move "Landed Cost Voucher" from `non_standard_fieldnames`
to `internal_links`, where Frappe's resolver walks the child table and
matches the field there (see notifications.py:326-332). After that, the
counter correctly walks LCV.purchase_receipts.receipt_document and
finds the PI.

Rahul 2026-05-22: prior signature was `def get_data():` (no kwargs).
Frappe v15 meta.py:672 calls every override_doctype_dashboards hook
as `frappe.get_attr(hook)(data=data)` — passing the previously-resolved
base data as a keyword arg so overrides can extend rather than replace.
The kwarg-less signature crashed every Purchase Invoice form load with
`TypeError: get_data() got an unexpected keyword argument 'data'`.
Fix: accept `data=None` and either mutate the passed dict (normal hook
call path) or fall back to fetching the ERPNext base when called
standalone (e.g. local unit smoke tests).
"""

from erpnext.accounts.doctype.purchase_invoice.purchase_invoice_dashboard import (
    get_data as _base_get_data,
)


def get_data(data=None):
    if data is None:
        data = _base_get_data()

    # Move LCV out of non_standard_fieldnames (which queries the parent
    # table) and into internal_links (which walks the child table).
    nsfn = data.get("non_standard_fieldnames") or {}
    if "Landed Cost Voucher" in nsfn:
        nsfn.pop("Landed Cost Voucher", None)
        data["non_standard_fieldnames"] = nsfn

    internal_links = data.get("internal_links") or {}
    internal_links["Landed Cost Voucher"] = ["purchase_receipts", "receipt_document"]
    data["internal_links"] = internal_links

    return data
