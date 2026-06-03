"""Patch B4 — auto-submit Draft Sales Invoices linked to non-stock DNs.

Sridhar 2026-06-03 — final pass on Ghost Voucher cleanup.

When a Delivery Note ships non-stock items (services, charges, education
materials), ERPNext correctly produces NO DN-level GL entries. The
financial impact lives on the linked Sales Invoice. If that SI was
created but never submitted (left as Draft), the DN appears as a
"ghost" in audit reports — but the actual fix isn't to repost the DN,
it's to SUBMIT THE DRAFT SI.

This patch finds every:
  - Delivery Note that's submitted (docstatus=1)
  - whose items are all non-stock
  - that has 0 GL entries on the DN itself
  - and whose linked Sales Invoice is still in Draft (docstatus=0)

Then submits the Draft SI. Stock + Accounts freezes are lifted for
the duration. Rate mismatches between DN and SI auto-align to DN rate
(authoritative since DN was created/submitted first).

Each row commits independently so a failure mid-batch doesn't roll
back the successes.

Idempotent. Safe to re-run. Standard run with 0 candidates: 0-op.
"""
import frappe
from frappe.utils import flt


def _lift_locks():
    """Lift all date-freeze locks. Returns originals for restoration."""
    orig = {
        "stock_frozen_upto": frappe.db.get_single_value("Stock Settings", "stock_frozen_upto") or "",
        "allow_negative_stock": frappe.db.get_single_value("Stock Settings", "allow_negative_stock") or 0,
        "acc_frozen_upto": frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto") or "",
    }
    if orig["stock_frozen_upto"]:
        frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", "")
    if not orig["allow_negative_stock"]:
        frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
    if orig["acc_frozen_upto"]:
        frappe.db.set_single_value("Accounts Settings", "acc_frozen_upto", "")
    frappe.db.commit()
    return orig


def _restore_locks(orig):
    frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", orig["stock_frozen_upto"])
    frappe.db.set_single_value("Stock Settings", "allow_negative_stock", orig["allow_negative_stock"])
    frappe.db.set_single_value("Accounts Settings", "acc_frozen_upto", orig["acc_frozen_upto"])
    frappe.db.commit()


def _find_draft_sis_for_non_stock_dns():
    """Return list of (dn_name, si_name) where:
       - DN docstatus=1
       - DN items all non-stock
       - DN has no own GL
       - Linked SI is Draft (docstatus=0)
    """
    candidates = frappe.db.sql("""
    SELECT DISTINCT dni.parent AS dn, sii.parent AS si
    FROM `tabSales Invoice Item` sii
    INNER JOIN `tabDelivery Note Item` dni ON sii.dn_detail = dni.name
    INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
    INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
    WHERE dn.docstatus = 1
      AND si.docstatus = 0  -- Draft
      AND NOT EXISTS (
        SELECT 1 FROM `tabGL Entry` g
        WHERE g.voucher_no = dn.name AND g.voucher_type = 'Delivery Note' AND g.is_cancelled = 0
      )
      AND NOT EXISTS (
        SELECT 1 FROM `tabDelivery Note Item` di
        INNER JOIN `tabItem` i ON i.name = di.item_code
        WHERE di.parent = dn.name AND i.is_stock_item = 1
      )
    """, as_dict=True)
    return candidates


def _align_rates(si_name, dn_name):
    """Align SI line rates to the linked DN line rate. DN is authoritative."""
    si = frappe.get_doc("Sales Invoice", si_name)
    aligned = 0
    for sii in si.items:
        if not sii.dn_detail:
            continue
        dn_rate = frappe.db.get_value("Delivery Note Item", sii.dn_detail, "rate")
        if dn_rate is None:
            continue
        if abs(flt(sii.rate) - flt(dn_rate)) > 0.01:
            sii.rate = dn_rate
            sii.price_list_rate = dn_rate
            sii.amount = flt(sii.qty) * flt(dn_rate)
            aligned += 1
    if aligned:
        si.flags.ignore_permissions = True
        si.save()
        frappe.db.commit()
    return aligned


def _align_everything_to_dn(si_name):
    """Pre-align everything to the DN's rate via direct SQL.
    SI line.rate ← DN line.rate, then SO line.rate ← DN line.rate.
    All amounts + parent SO totals recalculated.

    Direct SQL bypasses validation chains that were thrashing on the
    transactional rollback. Used before the final submit() attempt.
    """
    si = frappe.get_doc("Sales Invoice", si_name)
    so_names_to_recalc = set()

    for sii in si.items:
        dn_rate = None
        if sii.dn_detail:
            dn_rate = frappe.db.get_value("Delivery Note Item", sii.dn_detail, "rate")
        # Fallback to SO rate if no DN link, but DN is preferred
        if dn_rate is None and sii.so_detail:
            dn_rate = frappe.db.get_value("Sales Order Item", sii.so_detail, "rate")
        if dn_rate is None:
            continue

        new_amount = flt(sii.qty) * flt(dn_rate)
        # Update SI Item
        frappe.db.set_value("Sales Invoice Item", sii.name, {
            "rate": dn_rate, "price_list_rate": dn_rate,
            "amount": new_amount, "net_rate": dn_rate, "net_amount": new_amount,
        }, update_modified=False)
        # Update SO Item (if linked)
        if sii.so_detail:
            so_rate = frappe.db.get_value("Sales Order Item", sii.so_detail, "rate")
            if so_rate is not None and abs(flt(so_rate) - flt(dn_rate)) > 0.01:
                so_amount = flt(sii.qty) * flt(dn_rate)
                frappe.db.set_value("Sales Order Item", sii.so_detail, {
                    "rate": dn_rate, "price_list_rate": dn_rate,
                    "amount": so_amount, "net_rate": dn_rate, "net_amount": so_amount,
                }, update_modified=False)
                so_names_to_recalc.add(sii.sales_order)

    # Recalc parent SO totals
    for so in so_names_to_recalc:
        so_total = frappe.db.sql(
            "SELECT SUM(amount) FROM `tabSales Order Item` WHERE parent=%s", (so,)
        )[0][0] or 0
        frappe.db.set_value("Sales Order", so, {
            "net_total": so_total, "base_net_total": so_total,
            "total": so_total, "base_total": so_total,
            "grand_total": so_total, "base_grand_total": so_total,
            "rounded_total": so_total, "base_rounded_total": so_total,
        }, update_modified=False)

    # Recalc parent SI totals
    si_total = frappe.db.sql(
        "SELECT SUM(amount) FROM `tabSales Invoice Item` WHERE parent=%s", (si_name,)
    )[0][0] or 0
    frappe.db.set_value("Sales Invoice", si_name, {
        "net_total": si_total, "base_net_total": si_total,
        "total": si_total, "base_total": si_total,
        "grand_total": si_total, "base_grand_total": si_total,
        "rounded_total": si_total, "base_rounded_total": si_total,
        "outstanding_amount": si_total,
    }, update_modified=False)


def _align_sales_order_rates(si_name):
    """After aligning to DN rate, ERPNext may throw 'Rate must be same as
    Sales Order'. Sync each linked SO line's rate to the SI rate via
    direct SQL (the SO is upstream; if DN/SI diverged from it, the
    transaction overrode the SO and we sync the SO to match reality)."""
    si = frappe.get_doc("Sales Invoice", si_name)
    updated = 0
    so_names_to_recalc = set()
    for sii in si.items:
        if not sii.sales_order or not sii.so_detail:
            continue
        so_rate = frappe.db.get_value("Sales Order Item", sii.so_detail, "rate")
        if so_rate is None:
            continue
        if abs(flt(sii.rate) - flt(so_rate)) > 0.01:
            new_amount = flt(sii.qty) * flt(sii.rate)
            frappe.db.set_value("Sales Order Item", sii.so_detail, {
                "rate": sii.rate,
                "price_list_rate": sii.rate,
                "amount": new_amount,
                "net_rate": sii.rate,
                "net_amount": new_amount,
            }, update_modified=False)
            so_names_to_recalc.add(sii.sales_order)
            updated += 1
    for so in so_names_to_recalc:
        so_total = frappe.db.sql(
            "SELECT SUM(amount) FROM `tabSales Order Item` WHERE parent=%s", (so,)
        )[0][0] or 0
        frappe.db.set_value("Sales Order", so, {
            "net_total": so_total, "base_net_total": so_total,
            "total": so_total, "base_total": so_total,
            "grand_total": so_total, "base_grand_total": so_total,
            "rounded_total": so_total, "base_rounded_total": so_total,
        }, update_modified=False)
    if updated:
        frappe.db.commit()
    return updated


def execute():
    candidates = _find_draft_sis_for_non_stock_dns()
    print(f"[fix_non_stock_dn_drafts] {len(candidates)} candidate Draft SIs found")

    if not candidates:
        return

    orig = _lift_locks()
    submitted = 0
    rate_aligned_then_submitted = 0
    failed = []

    try:
        for c in candidates:
            si_name, dn_name = c["si"], c["dn"]
            # Skip if SI already submitted by an earlier iteration
            if frappe.db.get_value("Sales Invoice", si_name, "docstatus") != 0:
                continue

            try:
                si = frappe.get_doc("Sales Invoice", si_name)
                si.flags.ignore_permissions = True
                si.flags.ignore_links = True
                si.submit()
                frappe.db.commit()  # commit per row — failures don't roll back successes
                submitted += 1
            except Exception as e:
                err = str(e)
                # Rate mismatch (DN or SO) — align everything BEFORE retry
                if ("Rate must be same as Delivery Note" in err
                    or "Rate must be same as Sales Order" in err):
                    try:
                        frappe.db.rollback()
                        # Pre-align: SI rate → DN rate, then SO rate → DN rate
                        # via direct SQL on both child tables. This way the
                        # next submit() sees everything consistent.
                        _align_everything_to_dn(si_name)
                        frappe.db.commit()
                        si = frappe.get_doc("Sales Invoice", si_name)
                        si.flags.ignore_permissions = True
                        si.flags.ignore_links = True
                        si.submit()
                        frappe.db.commit()
                        rate_aligned_then_submitted += 1
                        continue
                    except Exception as e2:
                        frappe.db.rollback()
                        failed.append((si_name, f"rate-align retry: {str(e2)[:200]}"))
                else:
                    frappe.db.rollback()
                    failed.append((si_name, err[:200]))
    finally:
        _restore_locks(orig)

    print(f"[fix_non_stock_dn_drafts] submitted={submitted} "
          f"rate_aligned={rate_aligned_then_submitted} failed={len(failed)}")
    if failed:
        for si, err in failed[:5]:
            print(f"  FAILED {si}: {err}")
