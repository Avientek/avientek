"""Find (and optionally repair) Quotations where ERPNext's per-item margin
control has pulled item.rate away from custom_selling_price.

Reported as QN-LLC-26-01303 — "the Total selling price is showing 2 different
values". Totals section read AED 10,739.49 while the Brand Summary read
AED 8,677.85, apart by exactly 2 x 1,030.82: the manual margin on item
I030325 counted twice.

Mechanism
---------
margin_type / margin_rate_or_amount / rate_with_margin and the per-item
discount_percentage / discount_amount are ERPNext's own pricing model. This
app has its own (custom_special_price -> custom_cogs -> custom_markup_ ->
custom_selling_price) and never writes core's, but the Items grid's standard
margin control does. Core's calculate_item_values() then re-derives the rate:

    item.rate = rate_with_margin * (1 - discount_percentage/100)
    if discount_amount and not discount_percentage:
        item.rate = rate_with_margin - discount_amount        # (A)
    else:
        item.discount_amount = rate_with_margin - item.rate   # (B)

On a Draft save core runs in validate and run_calculation_pipeline runs later
in before_save, so our rate wins. On a submitted quote the "Approved for
Update" endpoints end with doc.calculate_taxes_and_totals(), so core's rate
wins instead — and (B), which measures against OUR rate, leaves a NEGATIVE
discount_amount that (A) then subtracts on the next save, adding the same
uplift again.

The fix (absorb_core_margin_fields, wired into both save paths) folds the
uplift into custom_markup_ and clears core's fields. It corrects a document
the next time that document is saved; this script is for finding the ones
already sitting in the wrong state, and for repairing them without waiting
for someone to open each quote.

Usage
-----
    # Report only — writes nothing. Start here.
    bench --site avientekv21.local execute \
        avientek.scripts.diag_quotation_core_margin_desync.run

    # Report a single quote in full detail
    bench --site avientekv21.local execute \
        avientek.scripts.diag_quotation_core_margin_desync.run \
        --kwargs "{'quotation': 'QN-LLC-26-01303'}"

    # Repair ONE named quote. Deliberately per-document: these are submitted,
    # priced, customer-facing records and a bulk rewrite is not a thing to
    # trigger from a diag script. Confirm the corrected figure with the
    # owning salesperson before running.
    bench --site avientekv21.local execute \
        avientek.scripts.diag_quotation_core_margin_desync.repair \
        --kwargs "{'quotation': 'QN-LLC-26-01303'}"
"""

import frappe
from frappe.utils import flt, cint

from avientek.events.quotation import (
    absorb_core_margin_fields,
    rebuild_brand_summary,
    recalc_doc_totals,
    set_margin_flags,
)


def _affected_item_rows(quotation=None):
    """Quotation Item rows carrying core margin fields or a negative discount.

    A negative discount_amount is the fingerprint of branch (B) above and is
    what makes the uplift compound, so it is worth flagging even on a row
    whose margin fields have since been cleared.
    """
    filters = {
        "docstatus": ["<", 2],
    }
    if quotation:
        filters["parent"] = quotation

    rows = frappe.get_all(
        "Quotation Item",
        filters=filters,
        fields=[
            "name", "parent", "idx", "item_code", "qty",
            "rate", "amount", "price_list_rate",
            "custom_selling_price", "custom_special_rate", "custom_cogs",
            "margin_type", "margin_rate_or_amount", "rate_with_margin",
            "discount_percentage", "discount_amount",
        ],
        limit_page_length=0,
    )

    out = []
    for r in rows:
        has_margin = r.margin_type and flt(r.margin_rate_or_amount)
        negative_discount = flt(r.discount_amount) < 0
        qty = max(cint(r.qty), 1)
        # The symptom itself: the line's rate no longer agrees with the
        # selling price the Brand Summary is built from.
        rate_gap = flt(flt(r.rate) * qty - flt(r.custom_selling_price), 2)

        if has_margin or negative_discount or abs(rate_gap) >= 0.01:
            r["_rate_gap"] = rate_gap
            r["_has_margin"] = bool(has_margin)
            r["_negative_discount"] = negative_discount
            out.append(r)
    return out


def _doc_totals(name):
    d = frappe.db.get_value(
        "Quotation", name,
        ["net_total", "grand_total", "custom_total_selling_new",
         "custom_total_margin_percent_new", "workflow_state", "status",
         "docstatus", "owner", "customer_name"],
        as_dict=True,
    ) or {}
    d["brand_summary_selling"] = sum(
        flt(v) for v in (
            frappe.get_all(
                "Quotation Brand Summary",
                filters={"parent": name},
                pluck="total_selling",
            ) or []
        )
    )
    return d


def run(quotation=None, limit=None):
    """Report every affected quote. Writes nothing."""
    rows = _affected_item_rows(quotation)
    if not rows:
        print("No Quotation Items carrying core margin / negative discount. Clean.")
        return

    by_parent = {}
    for r in rows:
        by_parent.setdefault(r.parent, []).append(r)

    names = sorted(by_parent)
    if limit:
        names = names[: cint(limit)]

    print(f"\n{len(rows)} affected item row(s) across {len(by_parent)} quotation(s)")
    if limit:
        print(f"(showing first {len(names)})")
    print("=" * 100)

    total_exposure = 0.0
    for name in names:
        t = _doc_totals(name)
        gap = flt(flt(t.get("net_total")) - flt(t.get("brand_summary_selling")), 2)
        total_exposure += abs(gap)

        print(f"\n{name}  [{t.get('workflow_state') or '-'} / {t.get('status') or '-'}"
              f" / docstatus {t.get('docstatus')}]  {t.get('customer_name') or ''}")
        print(f"    Totals section  net_total            : {flt(t.get('net_total')):>14,.2f}")
        print(f"    Brand Summary   total_selling (sum)  : {flt(t.get('brand_summary_selling')):>14,.2f}")
        print(f"    Parent field    custom_total_selling : {flt(t.get('custom_total_selling_new')):>14,.2f}")
        print(f"    DISAGREEMENT                         : {gap:>14,.2f}")
        print(f"    {'idx':>4} {'item_code':<12} {'qty':>4} {'rate':>12} "
              f"{'selling/qty':>12} {'margin':>10} {'disc_amt':>10}")
        for r in sorted(by_parent[name], key=lambda x: cint(x.idx)):
            qty = max(cint(r.qty), 1)
            flags = []
            if r["_has_margin"]:
                flags.append(f"{r.margin_type}")
            if r["_negative_discount"]:
                flags.append("NEG-DISC")
            print(f"    {cint(r.idx):>4} {(r.item_code or ''):<12} {qty:>4} "
                  f"{flt(r.rate):>12,.2f} {flt(r.custom_selling_price) / qty:>12,.2f} "
                  f"{flt(r.margin_rate_or_amount):>10,.2f} {flt(r.discount_amount):>10,.2f}"
                  f"  {' '.join(flags)}")

    print("\n" + "=" * 100)
    print(f"Total absolute disagreement across listed quotes: {total_exposure:,.2f}")
    print("\nRepair one at a time, after confirming the intended price with the")
    print("owning salesperson:")
    print("  bench --site <site> execute "
          "avientek.scripts.diag_quotation_core_margin_desync.repair "
          "--kwargs \"{'quotation': '<QN-...>'}\"")


def repair(quotation, dry_run=0):
    """Re-run the corrected calculation over one quotation and save it.

    Folds the core margin into custom_markup_, clears core's fields, rebuilds
    the Brand Summary and the parent totals, then lets ERPNext recompute taxes
    and grand total from the corrected rates. set_margin_flags() re-runs too,
    so the approval flags reflect the price actually being quoted rather than
    the understated Brand Summary figure the original approval saw.
    """
    doc = frappe.get_doc("Quotation", quotation)
    before = {
        "net_total": flt(doc.net_total),
        "grand_total": flt(doc.grand_total),
        "custom_total_selling_new": flt(doc.custom_total_selling_new),
        "rates": {it.idx: flt(it.rate) for it in doc.items},
    }

    absorb_core_margin_fields(
        doc,
        discount_total=flt(doc.custom_discount_amount_value),
        pre_discount_total=sum(flt(it.custom_selling_price) for it in doc.items),
    )
    rebuild_brand_summary(doc)
    set_margin_flags(doc)
    recalc_doc_totals(doc)
    doc.calculate_taxes_and_totals()
    doc.set_payment_schedule()
    doc.set_total_in_words()

    print(f"\n{quotation}")
    print(f"  {'idx':>4} {'rate before':>14} {'rate after':>14}")
    for it in doc.items:
        was = before["rates"].get(it.idx, 0)
        mark = "  <-- changed" if abs(was - flt(it.rate)) >= 0.01 else ""
        print(f"  {cint(it.idx):>4} {was:>14,.2f} {flt(it.rate):>14,.2f}{mark}")
    print(f"  net_total    {before['net_total']:>14,.2f} -> {flt(doc.net_total):>14,.2f}")
    print(f"  grand_total  {before['grand_total']:>14,.2f} -> {flt(doc.grand_total):>14,.2f}")
    print(f"  auto_approve_ok={cint(doc.custom_auto_approve_ok)} "
          f"level_1_approve_ok={cint(doc.custom_level_1_approve_ok)}")

    if cint(dry_run):
        print("\n  dry_run=1 — nothing written.")
        return

    doc.flags.ignore_validate_update_after_submit = True
    frappe.flags.through_update_item = True
    doc.save()
    frappe.db.commit()
    print("\n  Saved.")
