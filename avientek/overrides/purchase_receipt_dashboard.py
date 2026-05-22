"""Override the Purchase Receipt Connections panel to fix the Landed
Cost Voucher count.

Same root cause as purchase_invoice_dashboard.py: standard ERPNext
declares `"Landed Cost Voucher": "receipt_document"` in
`non_standard_fieldnames`, which queries the PARENT LCV table for a
column that lives on the CHILD `Landed Cost Purchase Receipt` doctype.
We move it to `internal_links` so Frappe walks the child table.

Rahul 2026-05-22: signature must be `def get_data(data=None)` because
Frappe v15 meta.py:672 calls every override_doctype_dashboards hook as
`frappe.get_attr(hook)(data=data)`. The previous kwarg-less signature
crashed every Purchase Receipt form load with `TypeError: get_data()
got an unexpected keyword argument 'data'` ("Good morning, we are not
able to access the purchase receipt from yesterday night, please
check"). Mutate the passed dict if provided; fetch base only as a
local-test fallback.
"""

from erpnext.stock.doctype.purchase_receipt.purchase_receipt_dashboard import (
    get_data as _base_get_data,
)


def get_data(data=None):
    if data is None:
        data = _base_get_data()

    nsfn = data.get("non_standard_fieldnames") or {}
    if "Landed Cost Voucher" in nsfn:
        nsfn.pop("Landed Cost Voucher", None)
        data["non_standard_fieldnames"] = nsfn

    internal_links = data.get("internal_links") or {}
    internal_links["Landed Cost Voucher"] = ["purchase_receipts", "receipt_document"]
    data["internal_links"] = internal_links

    return data
