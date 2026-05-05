"""Forensic for "Sales Invoice DocPerm vanishes after migrate" bug.

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.diag_docperm_removal.snapshot_before
    bench --site avientekv21.local migrate
    bench --site avientekv21.local execute \
        avientek.scripts.diag_docperm_removal.snapshot_after_and_diff

Snapshots are stored as JSON in
`apps/avientek/.tmp_diag/sales_invoice_docperm_<phase>.json`.
"""
from __future__ import annotations

import json
import os

import frappe


_DOCTYPES = ["Sales Invoice"]
_TMP = os.path.join(
    frappe.get_app_path("avientek"), "..", ".tmp_diag"
)


def _snapshot_rows():
    rows = []
    for dt in _DOCTYPES:
        # Custom DocPerm
        cdp = frappe.db.sql(
            """SELECT 'Custom' AS source, name, parent, role, permlevel,
                      `read`, `write`, `create`, `delete`, submit, cancel,
                      amend, `if_owner`, report, export, import, `share`,
                      `print`, `email`, `select`, creation, modified
               FROM `tabCustom DocPerm`
               WHERE parent = %s
               ORDER BY role, permlevel""",
            (dt,), as_dict=True,
        )
        for r in cdp:
            r["__dt"] = dt
            rows.append(r)
        # Standard DocPerm (the doctype's own permissions list)
        sdp = frappe.db.sql(
            """SELECT 'Std' AS source, name, parent, role, permlevel,
                      `read`, `write`, `create`, `delete`, submit, cancel,
                      amend, `if_owner`, report, export, import, `share`,
                      `print`, `email`, `select`
               FROM `tabDocPerm`
               WHERE parent = %s
               ORDER BY role, permlevel""",
            (dt,), as_dict=True,
        )
        for r in sdp:
            r["__dt"] = dt
            rows.append(r)
    return rows


def _save(rows, phase):
    os.makedirs(_TMP, exist_ok=True)
    path = os.path.join(_TMP, f"sales_invoice_docperm_{phase}.json")
    with open(path, "w") as fh:
        json.dump(rows, fh, indent=1, default=str)
    return path


def snapshot_before():
    """Snapshot every Custom DocPerm + Standard DocPerm row for the
    target doctypes, BEFORE running migrate."""
    rows = _snapshot_rows()
    path = _save(rows, "before")
    print(f"[diag] BEFORE snapshot: {len(rows)} rows -> {path}")
    print()
    print(f"  Custom DocPerm rows on Sales Invoice:")
    for r in rows:
        if r["source"] == "Custom":
            print(f"    {r['role']:30s} pl={r['permlevel']}  "
                  f"read={r['read']} write={r['write']} create={r['create']} "
                  f"submit={r.get('submit')} export={r.get('export')}  "
                  f"name={r['name']}")
    return rows


def snapshot_after_and_diff():
    """Snapshot AFTER migrate and diff against BEFORE."""
    after = _snapshot_rows()
    path_after = _save(after, "after")
    print(f"[diag] AFTER snapshot: {len(after)} rows -> {path_after}")

    path_before = os.path.join(_TMP, "sales_invoice_docperm_before.json")
    if not os.path.isfile(path_before):
        print("[diag] no BEFORE snapshot; run snapshot_before first")
        return

    with open(path_before) as fh:
        before = json.load(fh)

    # Build keys: (source, parent, role, permlevel)
    def _key(r):
        return (r["source"], r["parent"], r["role"], r["permlevel"])

    before_by_key = {_key(r): r for r in before}
    after_by_key = {_key(r): r for r in after}

    deleted = [k for k in before_by_key if k not in after_by_key]
    added = [k for k in after_by_key if k not in before_by_key]
    changed = []
    for k in before_by_key:
        if k not in after_by_key:
            continue
        b, a = before_by_key[k], after_by_key[k]
        diffs = {}
        for fld in ("read", "write", "create", "delete", "submit",
                    "cancel", "amend", "report", "export", "import",
                    "share", "print", "email", "select", "if_owner"):
            if b.get(fld) != a.get(fld):
                diffs[fld] = (b.get(fld), a.get(fld))
        if diffs:
            changed.append((k, diffs))

    print(f"\n  DELETED rows: {len(deleted)}")
    for k in deleted:
        b = before_by_key[k]
        print(f"    {k[0]:6s}  {k[2]:30s} pl={k[3]}  was: "
              f"read={b['read']} write={b['write']} export={b.get('export')}  "
              f"name={b['name']}")

    print(f"\n  ADDED rows: {len(added)}")
    for k in added:
        a = after_by_key[k]
        print(f"    {k[0]:6s}  {k[2]:30s} pl={k[3]}  new: "
              f"read={a['read']} write={a['write']} export={a.get('export')}  "
              f"name={a['name']}")

    print(f"\n  CHANGED rows: {len(changed)}")
    for k, diffs in changed:
        print(f"    {k[0]:6s}  {k[2]:30s} pl={k[3]}: {diffs}")

    return {
        "deleted": [list(k) for k in deleted],
        "added": [list(k) for k in added],
        "changed": [{"key": list(k), "diffs": d} for k, d in changed],
    }
