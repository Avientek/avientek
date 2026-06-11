"""Normalize corrupted None values on Single-doctype date/link fields that
ERPNext's frozen-date guards compare against.

Sridhar/Venkatesh 2026-06-11: DN LTD-26-27-00358 submit on prod threw
`TypeError: '<=' not supported between instances of 'datetime.date' and
'NoneType'` from
    erpnext/stock/doctype/stock_ledger_entry/stock_ledger_entry.py:252
    check_stock_frozen_date:
        getdate(self.posting_date) <= getdate(stock_settings.stock_frozen_upto)

`stock_settings.stock_frozen_upto` was in a state where the row exists
in `tabSingles` for Stock Settings but the stored value is the
ambiguous None — Frappe's display API surfaced the schema default
'0001-01-01' but the actual stored value couldn't be parsed by
`getdate()` cleanly. Likely left over from the 2026-06-03 ghost-voucher
repost cleanup which lifts and restores this field around its run; some
edge in the restore path stored None instead of ''. ERPNext's guard
`if stock_settings.stock_frozen_upto:` then evaluates the stored value
as truthy in some Frappe code paths (cached doc) but `getdate()` returns
None on the same value, producing the TypeError.

This patch normalises any None on the following Single-doctype fields
to an empty string. Empty string is unambiguous — every Frappe and
ERPNext guard treats it as falsy and short-circuits before any
date comparison.

Idempotent: re-runs on already-normalised settings produce no change.

Defensive: lives in the migrate path so any future patch that
accidentally re-introduces the corruption is corrected on the next
deploy.
"""
import frappe


_TARGETS = [
    ("Stock Settings",    "stock_frozen_upto"),
    ("Stock Settings",    "stock_auth_role"),
    ("Accounts Settings", "acc_frozen_upto"),
    ("Accounts Settings", "frozen_accounts_modifier"),
]


def execute():
    fixed = 0
    for doctype, field in _TARGETS:
        cur = frappe.db.get_single_value(doctype, field)
        # `is None` is the exact failure mode — falsy strings ('', '0')
        # are fine; ERPNext's `if value:` guards already handle those.
        if cur is None:
            frappe.db.set_single_value(doctype, field, "")
            fixed += 1
            print(f"[normalize_freeze_setting_nones] {doctype}.{field}: "
                  f"None -> '' (was {cur!r})")
    if fixed:
        frappe.db.commit()
        # Clear meta caches so the next request reads the corrected
        # singles row instead of a stale cached doc.
        for doctype, _ in _TARGETS:
            try:
                frappe.clear_cache(doctype=doctype)
            except Exception:
                pass
    print(f"[normalize_freeze_setting_nones] done. fixed={fixed}")
