# Copyright (c) 2026, QCS
"""
Backfill `Sales Order.custom_submission_datetime` for HISTORICAL submitted
Sales Orders (those submitted before the on-submit stamp hook went live on
2026-08-03), so the Avientek Stock Allocation report (CR-01) can show and
allocate by the real submission timestamp instead of falling back to the
order booking date.

Source of truth: Frappe's own `Version` log. Every submit writes a Version
record whose `data.changed` contains `["docstatus", 0, 1]`; that record's
`creation` IS the moment the order was submitted. (Verified 100% present on
a 300-SO sample of recent historical orders on a prod-data restore.)

Report-only impact: `custom_submission_datetime` is a `no_copy` field read
only by the Stock Allocation report's sort/display — it does not touch any
document, stock ledger, or GL. `update_modified=False` so the SO's own
`modified` timestamp is left untouched.

Usage (dry-run by default — prints counts, writes nothing):
    bench --site <site> execute \
        avientek.scripts.backfill_so_submission_datetime.run
Live run:
    bench --site <site> execute \
        avientek.scripts.backfill_so_submission_datetime.run --kwargs "{'commit': True}"
Optional 'limit' kwarg caps how many SOs are processed (for a trial batch).
"""
import json
import frappe


def _submit_timestamp_from_version(so_name):
    """Return the creation time of the Version row that recorded this Sales
    Order's docstatus 0 -> 1 change, or None if no such record exists."""
    versions = frappe.get_all(
        "Version",
        filters={"ref_doctype": "Sales Order", "docname": so_name},
        fields=["name", "creation"],
        order_by="creation asc",
    )
    for v in versions:
        data = frappe.db.get_value("Version", v.name, "data")
        try:
            changed = (json.loads(data or "{}")).get("changed") or []
        except Exception:
            continue
        for c in changed:
            # c == ["docstatus", <old>, <new>]
            if c and c[0] == "docstatus" and c[2] == 1:
                return v.creation
    return None


def run(commit=False, limit=None):
    names = frappe.get_all(
        "Sales Order",
        filters={"docstatus": 1, "custom_submission_datetime": ["is", "not set"]},
        pluck="name",
        order_by="creation desc",
        limit_page_length=(int(limit) if limit else 0),
    )
    total = len(names)
    filled = recovered = no_version = 0

    for i, name in enumerate(names, 1):
        ts = _submit_timestamp_from_version(name)
        if not ts:
            no_version += 1
            continue
        recovered += 1
        if commit:
            frappe.db.set_value(
                "Sales Order", name, "custom_submission_datetime", ts,
                update_modified=False,
            )
            filled += 1
        if commit and i % 500 == 0:
            frappe.db.commit()
            print(f"  ... {i}/{total} processed, {filled} filled")

    if commit:
        frappe.db.commit()

    mode = "LIVE (written)" if commit else "DRY-RUN (nothing written)"
    print(f"[backfill_so_submission_datetime] {mode}")
    print(f"  historical NULL SOs scanned : {total}")
    print(f"  recoverable from Version log : {recovered}")
    print(f"  no Version record (left NULL): {no_version}")
    print(f"  written                      : {filled}")
