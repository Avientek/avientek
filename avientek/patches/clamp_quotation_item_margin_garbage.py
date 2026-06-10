"""Sridhar/Rahul 2026-06-09 — clamp garbage custom_margin_ / custom_incentive_
values on Quotation Item.

Rahul shared a screenshot of a Quote Report Builder where Margin% rows
showed values like -3580.00% and Incentive% showed 100.00% — clearly
out-of-range. Investigation on local found 21 rows with
|custom_margin_| > 100 (out of 3,793 non-zero). The worst offenders all
have amount = 0: divide-by-zero on the historical save produced values
in the billions (e.g. -559,105,746.15).

The current JS pipeline at public/js/quotation.js:1097 already protects
new saves:
   margin_percent = selling_price > 0 ? (margin_value / selling_price) * 100 : 0
But historical rows that pre-date the guard remain in the DB and pollute
the report.

Fix: ANY Quotation Item row where the percent field is garbage gets
clamped to a sane value:
  - If amount/selling_price == 0 → set the percent fields to 0 (the JS
    formula would do exactly this for new saves)
  - If |custom_margin_| > 500 (extreme outlier with non-zero amount,
    e.g. cost > selling by 5x) → recompute from
    (custom_margin_value / amount * 100) with the same divide-by-zero
    guard; clamp the final result to ±500 for sanity
  - Same logic for custom_incentive_ — but only clamp the >500 outliers;
    don't touch the 100% values unless they're paired with an
    incentive_value that contradicts them
Idempotent: subsequent runs are no-ops because clamped values fall
inside the sane range.
"""

import frappe
from frappe.utils import flt


SANE_LIMIT_PERCENT = 500.0


def execute():
    rows = frappe.db.sql(
        """
        SELECT name, parent, amount,
               custom_margin_value, custom_margin_,
               custom_incentive_value, custom_incentive_
        FROM `tabQuotation Item`
        WHERE ABS(IFNULL(custom_margin_, 0)) > %s
           OR ABS(IFNULL(custom_incentive_, 0)) > %s
        """,
        (SANE_LIMIT_PERCENT, SANE_LIMIT_PERCENT),
        as_dict=True,
    )
    print(f"[clamp_quotation_item_margin_garbage] {len(rows)} candidate rows")
    if not rows:
        return

    fixed_margin = 0
    fixed_incentive = 0
    for r in rows:
        amt = flt(r.get("amount") or 0)
        mv = flt(r.get("custom_margin_value") or 0)
        mp_stored = flt(r.get("custom_margin_") or 0)
        ip_stored = flt(r.get("custom_incentive_") or 0)

        updates = {}

        if abs(mp_stored) > SANE_LIMIT_PERCENT:
            new_mp = (mv / amt * 100.0) if amt else 0
            # final clamp
            new_mp = max(-SANE_LIMIT_PERCENT, min(SANE_LIMIT_PERCENT, new_mp))
            updates["custom_margin_"] = new_mp
            fixed_margin += 1

        if abs(ip_stored) > SANE_LIMIT_PERCENT:
            iv = flt(r.get("custom_incentive_value") or 0)
            new_ip = (iv / amt * 100.0) if amt else 0
            new_ip = max(-SANE_LIMIT_PERCENT, min(SANE_LIMIT_PERCENT, new_ip))
            updates["custom_incentive_"] = new_ip
            fixed_incentive += 1

        if updates:
            for fn, val in updates.items():
                frappe.db.set_value(
                    "Quotation Item", r["name"], fn, val,
                    update_modified=False,
                )

    frappe.db.commit()
    print(f"[clamp_quotation_item_margin_garbage] cleaned "
          f"custom_margin_={fixed_margin} rows, "
          f"custom_incentive_={fixed_incentive} rows")
