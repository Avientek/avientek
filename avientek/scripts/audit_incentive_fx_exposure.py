"""DRY RUN / audit — Reward & Incentive JVs booked WITHOUT currency conversion.

Bug (fixed forward in c1d473f): book_reward_incentive_jv posted the Quote's
reward/incentive in the QUOTE's currency (e.g. USD) straight into
company-currency (AED) accounts, so every foreign-currency quote booked an
understated JV (2,480 USD posted as 2,480 AED instead of AED 9,107.80).

This script CHANGES NOTHING. It reports, per affected Sales Invoice:
    quote, currency, rate, JV, old booked amount -> correct amount, delta

Run:  bench --site <site> execute avientek.scripts.audit_incentive_fx_exposure.run
"""

import frappe
from frappe.utils import flt

from avientek.events.sales_invoice_reward_incentive import (
    _compute_itemwise,
    _compute_quotationwise,
    _load_settings,
    _resolve_quotation_for_si,
)

_SI_JV_FIELD = "custom_reward_incentive_jv"


def run():
    sis = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, _SI_JV_FIELD: ["not in", ("", None)]},
        fields=["name", "company", "currency"],
        order_by="posting_date",
    )
    print(f"Submitted SIs with a booked Reward/Incentive JV: {len(sis)}")

    affected, skipped_ok, total_old, total_new = [], 0, 0.0, 0.0

    for row in sis:
        si = frappe.get_doc("Sales Invoice", row.name)
        jv_name = si.get(_SI_JV_FIELD)
        jv = frappe.db.get_value(
            "Journal Entry", jv_name, ["docstatus", "total_debit"], as_dict=True
        )
        if not jv or jv.docstatus != 1:
            continue  # missing or already cancelled

        quote = _resolve_quotation_for_si(si)
        if not quote:
            continue

        rate = flt(quote.get("conversion_rate")) or 1.0
        if abs(rate - 1.0) < 1e-9:
            skipped_ok += 1  # company-currency quote — always booked correctly
            continue

        settings = _load_settings(si.company)
        if not settings:
            continue
        if settings["method"] == "Item Wise":
            r, i = _compute_itemwise(si, quote)
        else:
            r, i = _compute_quotationwise(si, quote)

        new_total = flt((flt(r) + flt(i)) * rate, 2)
        old_total = flt(jv.total_debit, 2)
        if new_total <= 0 or abs(new_total - old_total) < 0.01:
            continue

        affected.append(
            {
                "si": si.name, "company": si.company, "quote": quote.name,
                "ccy": quote.currency, "rate": rate, "jv": jv_name,
                "old": old_total, "new": new_total, "delta": flt(new_total - old_total, 2),
            }
        )
        total_old += old_total
        total_new += new_total

    print(f"Company-currency SIs (correct, untouched): {skipped_ok}")
    print(f"\n=== AFFECTED (foreign-currency, understated): {len(affected)} ===")
    if affected:
        print(f"{'Sales Invoice':<26}{'Quote':<24}{'Ccy':<5}{'Rate':<9}{'old':>12}{'correct':>13}{'delta':>13}")
        for a in affected:
            print(f"{a['si']:<26}{a['quote']:<24}{a['ccy']:<5}{a['rate']:<9}"
                  f"{a['old']:>12,.2f}{a['new']:>13,.2f}{a['delta']:>13,.2f}")
        print(f"\nTOTAL booked (understated): {total_old:>14,.2f}")
        print(f"TOTAL correct:              {total_new:>14,.2f}")
        print(f"TOTAL understatement:       {flt(total_new - total_old, 2):>14,.2f}")
        by_co = {}
        for a in affected:
            by_co.setdefault(a["company"], [0, 0.0])
            by_co[a["company"]][0] += 1
            by_co[a["company"]][1] += a["delta"]
        print("\nBy company:")
        for co, (n, d) in by_co.items():
            print(f"   {co:<28} {n:>3} JV(s)   understated by {d:>12,.2f}")
    print("\n(DRY RUN — nothing was changed.)")
