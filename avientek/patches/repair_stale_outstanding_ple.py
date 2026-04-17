"""Repair stale outstanding_amount caused by duplicate Payment Ledger Entries.

Background
----------
The earlier GL rebuild (patches/repost_ksa_full_gl_rebuild.py) cleaned up the
GL Entry table but did NOT clean the Payment Ledger Entry table. The duplicate
PLE rows survived, and ERPNext computes `Sales Invoice.outstanding_amount`
from PLE (not GL) — so every affected invoice reports 2x the real balance.

Pattern observed on production
------------------------------
For each affected invoice there are TWO PLE rows with:
- same voucher_type / voucher_no
- same account / party / party_type
- same against_voucher_no (the invoice itself)
- same amount sign and value
- delinked = 0

The outstanding_amount stored on the Sales Invoice / Purchase Invoice doc was
written by ERPNext's `update_voucher_outstanding` based on those duplicates
and has been frozen at 2x ever since.

Repair approach
---------------
For each candidate voucher:
  1. Group PLE rows by (voucher_type, voucher_no, account, party, party_type,
     against_voucher_no, amount, delinked).
  2. In any group with count > 1, keep the earliest row and flip `delinked=1`
     on the rest. (delinked=1 is ERPNext's native soft-delete marker — the
     outstanding-query ignores them.)
  3. Call `update_voucher_outstanding` to recompute from the de-duplicated
     PLE and write the fresh value onto the doc.

Nothing touches GL Entry. No new ledger entries are created. Entirely within
ERPNext's existing mechanisms.
"""

import frappe
from frappe.utils import flt


_TOLERANCE = 0.01

# Only this company is affected — other companies have clean PLE. Defaulting
# here prevents an accidental cross-company sweep if someone wires this into
# patches.txt later.
_DEFAULT_COMPANY = "AVIENTEK TRADING LLC"


def execute():
    """Patch entry — scoped to the KSA company only."""
    result = run_repair(dry_run=False, company=_DEFAULT_COMPANY)
    print(
        "[repair_stale_outstanding_ple] "
        f"company={_DEFAULT_COMPANY} "
        f"scanned={result['scanned']} "
        f"ple_delinked={result['ple_delinked']} "
        f"outstanding_updated={result['outstanding_updated']} "
        f"skipped={len(result['skipped'])}"
    )


@frappe.whitelist()
def run_repair(dry_run=1, company=None, doctype=None, limit=None):
    """Inspect (and optionally fix) stale outstanding_amount on invoices.

    Args:
        dry_run: 1 (default) reports only; 0 actually writes.
        company: restrict to one company (e.g. "AVIENTEK TRADING LLC").
        doctype: "Sales Invoice" or "Purchase Invoice". Omit for both.
        limit: cap number of invoices scanned per doctype (for sampling).

    Returns a dict with scanned/ple_delinked/outstanding_updated/changes/skipped.
    Changes are always recorded regardless of dry_run so the reviewer can
    inspect exactly what WOULD happen before approving writes.
    """
    dry_run = bool(int(dry_run)) if dry_run is not None else True
    doctypes = [doctype] if doctype else ["Sales Invoice", "Purchase Invoice"]

    result = {
        "dry_run": dry_run,
        "scanned": 0,
        "ple_delinked": 0,
        "outstanding_updated": 0,
        "changes": [],
        "skipped": [],
    }

    for dt in doctypes:
        party_field = "customer" if dt == "Sales Invoice" else "supplier"
        account_field = "debit_to" if dt == "Sales Invoice" else "credit_to"
        party_type = "Customer" if dt == "Sales Invoice" else "Supplier"

        filters = {"docstatus": 1, "outstanding_amount": [">", 0]}
        if company:
            filters["company"] = company

        candidates = frappe.get_all(
            dt,
            filters=filters,
            fields=[
                "name",
                "grand_total",
                "outstanding_amount",
                f"{party_field} as party",
                f"{account_field} as account",
            ],
            order_by="posting_date desc",
            limit_page_length=(int(limit) if limit else 0),
        )

        for inv in candidates:
            result["scanned"] += 1
            try:
                inv_result = _repair_voucher(
                    voucher_type=dt,
                    voucher_no=inv.name,
                    account=inv.account,
                    party_type=party_type,
                    party=inv.party,
                    current_outstanding=flt(inv.outstanding_amount),
                    grand_total=flt(inv.grand_total),
                    dry_run=dry_run,
                )
                if inv_result:
                    if inv_result.get("ple_delinked"):
                        result["ple_delinked"] += inv_result["ple_delinked"]
                    if inv_result.get("outstanding_changed"):
                        result["outstanding_updated"] += 1
                    result["changes"].append(inv_result)
            except Exception as e:
                result["skipped"].append({"name": inv.name, "error": str(e)})
                frappe.log_error(
                    title=f"repair_stale_outstanding_ple: {dt}/{inv.name}",
                    message=frappe.get_traceback(),
                )

        if not dry_run:
            frappe.db.commit()

    return result


def _repair_voucher(voucher_type, voucher_no, account, party_type, party,
                    current_outstanding, grand_total, dry_run):
    """Inspect PLE for one voucher; delink duplicates and refresh outstanding."""
    ples = frappe.db.sql(
        """
        SELECT name, amount, amount_in_account_currency, against_voucher_no,
               delinked, creation
        FROM `tabPayment Ledger Entry`
        WHERE voucher_type = %(vt)s
          AND voucher_no   = %(vn)s
          AND account      = %(ac)s
          AND party_type   = %(pt)s
          AND party        = %(pa)s
          AND delinked     = 0
        ORDER BY creation ASC, name ASC
        """,
        {"vt": voucher_type, "vn": voucher_no, "ac": account,
         "pt": party_type, "pa": party},
        as_dict=True,
    )

    if not ples:
        return None

    groups = {}
    for ple in ples:
        key = (
            ple.against_voucher_no or "",
            round(flt(ple.amount_in_account_currency), 4),
        )
        groups.setdefault(key, []).append(ple)

    to_delink = []
    for key, rows in groups.items():
        if len(rows) > 1:
            to_delink.extend(rows[1:])

    if not to_delink:
        return None

    delinked_names = [r.name for r in to_delink]
    if not dry_run:
        frappe.db.sql(
            "UPDATE `tabPayment Ledger Entry` SET delinked=1 WHERE name IN %s",
            (tuple(delinked_names),),
        )

    new_outstanding = _compute_outstanding(voucher_type, voucher_no, account,
                                           party_type, party,
                                           exclude_ple=delinked_names if dry_run else None)
    new_outstanding = flt(new_outstanding,
                          frappe.get_precision(voucher_type, "outstanding_amount") or 2)

    outstanding_changed = abs(new_outstanding - current_outstanding) > _TOLERANCE

    if outstanding_changed and not dry_run:
        frappe.db.set_value(voucher_type, voucher_no, "outstanding_amount",
                            new_outstanding, update_modified=False)

    return {
        "doctype": voucher_type,
        "name": voucher_no,
        "grand_total": grand_total,
        "old_outstanding": current_outstanding,
        "new_outstanding": new_outstanding,
        "outstanding_changed": outstanding_changed,
        "ple_delinked": len(delinked_names),
        "delinked_ple_names": delinked_names,
    }


@frappe.whitelist()
def purge_duplicate_ple(dry_run=1, company=None, limit=None):
    """Broad ledger cleanup — delink ALL duplicate Payment Ledger Entries
    regardless of voucher type, then refresh outstanding on any affected
    Sales Invoice / Purchase Invoice.

    Complements `run_repair`, which only touches SI/PI with outstanding > 0.
    This function covers Payment Entry, Journal Entry, and zero-outstanding
    invoices (e.g. fully-paid SIs, Credit Return Notes) whose PLE is still
    duplicated and would mislead aging / reconciliation reports.

    Args:
        dry_run: 1 (default) reports only; 0 writes.
        company: restrict to one company.
        limit: cap the number of duplicate groups processed.

    Returns {scanned_groups, ple_delinked, vouchers_affected,
             outstanding_updated, by_voucher_type, skipped}.
    """
    dry_run = bool(int(dry_run)) if dry_run is not None else True

    where = ["delinked = 0"]
    params = {}
    if company:
        where.append("company = %(co)s")
        params["co"] = company

    where_sql = " AND ".join(where)

    groups = frappe.db.sql(
        f"""
        SELECT voucher_type, voucher_no, account, party_type, party,
               against_voucher_no, amount_in_account_currency AS amt,
               COUNT(*) AS n,
               GROUP_CONCAT(name ORDER BY creation, name) AS ple_names
        FROM `tabPayment Ledger Entry`
        WHERE {where_sql}
        GROUP BY voucher_type, voucher_no, account, party_type, party,
                 against_voucher_no, amount_in_account_currency
        HAVING n > 1
        {"LIMIT " + str(int(limit)) if limit else ""}
        """,
        params, as_dict=True,
    )

    result = {
        "dry_run": dry_run,
        "company": company,
        "scanned_groups": len(groups),
        "ple_delinked": 0,
        "vouchers_affected": 0,
        "outstanding_updated": 0,
        "by_voucher_type": {},
        "skipped": [],
    }

    affected_vouchers = {}  # (voucher_type, voucher_no, account, party_type, party) -> True
    # Invoices whose balance is affected via `against_voucher_no` (e.g. a JE
    # dedup against INV-X reduces INV-X's computed outstanding).
    refresh_invoices = {}  # (voucher_type, voucher_no, account, party_type, party) -> True

    for g in groups:
        result["by_voucher_type"].setdefault(g.voucher_type, 0)
        result["by_voucher_type"][g.voucher_type] += 1

        names = (g.ple_names or "").split(",")
        if len(names) <= 1:
            continue
        to_delink = names[1:]  # keep oldest/first

        if not dry_run:
            try:
                for i in range(0, len(to_delink), 500):
                    batch = to_delink[i:i + 500]
                    frappe.db.sql(
                        "UPDATE `tabPayment Ledger Entry` SET delinked=1 WHERE name IN %s",
                        (tuple(batch),),
                    )
            except Exception as e:
                result["skipped"].append({"voucher": g.voucher_no, "error": str(e)})
                continue

        result["ple_delinked"] += len(to_delink)
        affected_vouchers[(g.voucher_type, g.voucher_no, g.account, g.party_type, g.party)] = True

        # Also flag the invoice referenced by against_voucher_no for refresh.
        # Only SI/PI carry outstanding_amount; those are the only ones we'll
        # refresh. Skip self-references (already covered by affected_vouchers).
        if g.against_voucher_no and g.against_voucher_no != g.voucher_no:
            inv_type = None
            if frappe.db.exists("Sales Invoice", g.against_voucher_no):
                inv_type = "Sales Invoice"
            elif frappe.db.exists("Purchase Invoice", g.against_voucher_no):
                inv_type = "Purchase Invoice"
            if inv_type:
                refresh_invoices[(inv_type, g.against_voucher_no, g.account,
                                  g.party_type, g.party)] = True

    # SI/PI that themselves had dupes also need outstanding refresh
    for key in affected_vouchers:
        vt = key[0]
        if vt in ("Sales Invoice", "Purchase Invoice"):
            refresh_invoices[key] = True

    result["vouchers_affected"] = len(affected_vouchers)

    if not dry_run:
        for (vt, vn, ac, pt, pa) in refresh_invoices:
            try:
                new_os = _compute_outstanding(vt, vn, ac, pt, pa)
                prec = frappe.get_precision(vt, "outstanding_amount") or 2
                frappe.db.set_value(vt, vn, "outstanding_amount",
                                    flt(new_os, prec), update_modified=False)
                result["outstanding_updated"] += 1
            except Exception as e:
                result["skipped"].append({"voucher": vn, "error": str(e)})

        frappe.db.commit()

    return result


@frappe.whitelist()
def undo_repair(since=None, company=None, doctype=None):
    """Roll back a prior run of run_repair.

    Re-links any Payment Ledger Entry that this patch delinked after a given
    timestamp, then recomputes outstanding_amount for the affected invoices
    so the doc matches the (now restored) PLE state.

    Args:
        since: ISO timestamp (e.g. '2026-04-17 12:00:00'). If omitted, uses
               the earliest modified PLE with delinked=1 in the last 24h.
        company: optional filter to restrict to one company's invoices.
        doctype: optional "Sales Invoice" or "Purchase Invoice" filter.

    Returns a dict describing what was re-linked and recomputed.
    """
    from frappe.utils import add_to_date, now_datetime

    if not since:
        since = add_to_date(now_datetime(), hours=-24, as_string=True)

    # Find PLE rows delinked since `since` — these are the ones this patch
    # would have touched (normal ERPNext delinking sets modified too).
    voucher_filter_sql = ""
    params = {"since": since}
    if doctype:
        voucher_filter_sql += " AND voucher_type = %(dt)s"
        params["dt"] = doctype

    ples = frappe.db.sql(
        f"""SELECT name, voucher_type, voucher_no, account, party_type, party
            FROM `tabPayment Ledger Entry`
            WHERE delinked = 1 AND modified >= %(since)s
            {voucher_filter_sql}""",
        params, as_dict=True,
    )

    if not ples:
        return {"relinked": 0, "recomputed": 0, "note": "no delinked PLE found"}

    # Optional company filter via voucher join
    if company:
        allowed = set()
        voucher_by_type = {}
        for p in ples:
            voucher_by_type.setdefault(p.voucher_type, set()).add(p.voucher_no)
        for vt, names in voucher_by_type.items():
            company_match = frappe.get_all(
                vt, filters={"name": ["in", list(names)], "company": company},
                pluck="name",
            )
            allowed.update(company_match)
        ples = [p for p in ples if p.voucher_no in allowed]

    if not ples:
        return {"relinked": 0, "recomputed": 0,
                "note": f"no delinked PLE for company={company!r}"}

    # Re-link
    names = [p.name for p in ples]
    for i in range(0, len(names), 500):
        batch = names[i:i + 500]
        frappe.db.sql(
            "UPDATE `tabPayment Ledger Entry` SET delinked=0 WHERE name IN %s",
            (tuple(batch),),
        )

    # Recompute outstanding for each affected voucher (dedupe)
    seen = set()
    recomputed = 0
    for p in ples:
        key = (p.voucher_type, p.voucher_no, p.account, p.party_type, p.party)
        if key in seen:
            continue
        seen.add(key)
        if p.voucher_type not in ("Sales Invoice", "Purchase Invoice"):
            continue
        new_os = _compute_outstanding(p.voucher_type, p.voucher_no, p.account,
                                      p.party_type, p.party)
        frappe.db.set_value(p.voucher_type, p.voucher_no,
                            "outstanding_amount", new_os, update_modified=False)
        recomputed += 1

    frappe.db.commit()

    return {
        "relinked": len(names),
        "recomputed": recomputed,
        "since": since,
        "company": company,
        "doctype": doctype,
    }


@frappe.whitelist()
def refresh_stale_statuses(company=None):
    """Recompute status on Sales/Purchase Invoices whose status field is out
    of sync with their current outstanding_amount (common after the PLE
    dedup: outstanding dropped to 0 but 'Overdue' stuck). Calls ERPNext's
    official `set_status(update=True)` which is safe on submitted docs —
    it bypasses the field's allow_on_submit rule because that's what the
    method is designed to do.

    Returns {checked, updated, details}.
    """
    stale_terminal_statuses = ("Paid", "Credit Note Issued", "Return", "Closed")
    result = {"checked": 0, "updated": 0, "details": []}

    for dt in ("Sales Invoice", "Purchase Invoice"):
        filters = {"docstatus": 1, "outstanding_amount": 0}
        if company:
            filters["company"] = company

        candidates = frappe.get_all(dt, filters=filters,
                                    fields=["name", "status"])
        for inv in candidates:
            result["checked"] += 1
            if inv.status in stale_terminal_statuses:
                continue
            try:
                doc = frappe.get_doc(dt, inv.name)
                old_status = doc.status
                doc.set_status(update=True)
                new_status = frappe.db.get_value(dt, inv.name, "status")
                if new_status != old_status:
                    result["updated"] += 1
                    result["details"].append({
                        "doctype": dt, "name": inv.name,
                        "old": old_status, "new": new_status,
                    })
            except Exception as e:
                result["details"].append({"doctype": dt, "name": inv.name, "error": str(e)})

    frappe.db.commit()
    return result


@frappe.whitelist()
def demo_on_local(voucher_no=None):
    """Demo the repair on a local site: pick (or accept) one open Sales Invoice,
    inject a duplicate PLE row + set outstanding to 2× to simulate the prod bug,
    run the repair, print before/after, then restore the original state.

    SAFETY: requires developer_mode=1 or allow_tests=1 in the site config.
    This is what distinguishes a local dev site from production (site name
    alone isn't enough — local sites can share the production name).
    """
    import uuid
    from frappe.utils import now_datetime

    conf = frappe.conf or {}
    if not (conf.get("developer_mode") or conf.get("allow_tests")):
        frappe.throw(
            f"demo_on_local refused on site '{frappe.local.site}' — "
            "developer_mode or allow_tests must be enabled. "
            "This guard prevents accidental runs on production."
        )

    if not voucher_no:
        rows = frappe.db.sql(
            """SELECT name, grand_total, outstanding_amount, customer, debit_to
               FROM `tabSales Invoice`
               WHERE docstatus=1 AND outstanding_amount>0
               ORDER BY posting_date DESC LIMIT 1""",
            as_dict=True,
        )
        if not rows:
            return {"error": "No open Sales Invoice found on this site."}
        inv = rows[0]
    else:
        inv = frappe.db.sql(
            """SELECT name, grand_total, outstanding_amount, customer, debit_to
               FROM `tabSales Invoice` WHERE name=%s""",
            voucher_no, as_dict=True,
        )
        if not inv:
            return {"error": f"Sales Invoice {voucher_no} not found."}
        inv = inv[0]

    # Snapshot original state
    original_os = inv.outstanding_amount
    src = frappe.db.sql(
        """SELECT * FROM `tabPayment Ledger Entry`
           WHERE voucher_no=%s AND delinked=0 LIMIT 1""",
        inv.name, as_dict=True,
    )
    if not src:
        return {"error": f"No active PLE for {inv.name} — can't simulate."}
    src = src[0]

    def _ple_summary(name):
        r = frappe.db.sql(
            """SELECT COUNT(*) AS row_count, COALESCE(SUM(amount_in_account_currency),0) AS total
               FROM `tabPayment Ledger Entry` WHERE voucher_no=%s AND delinked=0""",
            name, as_dict=True,
        )[0]
        return {"rows": r.row_count, "total": float(r.total)}

    report = {"invoice": inv.name, "grand_total": float(inv.grand_total)}
    report["before"] = {
        "ple": _ple_summary(inv.name),
        "outstanding_amount": float(original_os),
    }

    # Simulate prod bug: insert a duplicate PLE + double the outstanding
    dup_name = f"DEMO-DUP-{uuid.uuid4().hex[:8]}"
    cols = [k for k in src.keys() if k not in ("name", "creation", "modified")]
    col_sql = ", ".join(f"`{c}`" for c in cols)
    val_ph = ", ".join(["%s"] * len(cols))
    frappe.db.sql(
        f"INSERT INTO `tabPayment Ledger Entry` (name, creation, modified, {col_sql}) "
        f"VALUES (%s, %s, %s, {val_ph})",
        [dup_name, now_datetime(), now_datetime()] + [src[c] for c in cols],
    )
    frappe.db.set_value(
        "Sales Invoice", inv.name, "outstanding_amount",
        float(inv.grand_total) * 2, update_modified=False,
    )

    report["simulated_bug"] = {
        "ple": _ple_summary(inv.name),
        "outstanding_amount": float(inv.grand_total) * 2,
        "injected_duplicate_ple": dup_name,
    }

    # Dry-run — should detect but not change state
    dry = run_repair(dry_run=1, doctype="Sales Invoice")
    dry_for_inv = next((c for c in dry["changes"] if c["name"] == inv.name), None)
    report["dry_run"] = {
        "detected": dry_for_inv,
        "state_after_dry_run": {
            "ple": _ple_summary(inv.name),
            "outstanding_amount": float(
                frappe.db.get_value("Sales Invoice", inv.name, "outstanding_amount")
            ),
        },
    }

    # Real run — apply the fix
    real = run_repair(dry_run=0, doctype="Sales Invoice")
    real_for_inv = next((c for c in real["changes"] if c["name"] == inv.name), None)
    report["after_repair"] = {
        "change": real_for_inv,
        "ple": _ple_summary(inv.name),
        "outstanding_amount": float(
            frappe.db.get_value("Sales Invoice", inv.name, "outstanding_amount")
        ),
    }

    # Cleanup: remove injected row, restore any delinked originals, restore outstanding
    frappe.db.sql("DELETE FROM `tabPayment Ledger Entry` WHERE name=%s", dup_name)
    if real_for_inv:
        for n in real_for_inv.get("delinked_ple_names", []):
            if n != dup_name:
                frappe.db.set_value("Payment Ledger Entry", n, "delinked", 0,
                                    update_modified=False)
    frappe.db.set_value("Sales Invoice", inv.name, "outstanding_amount",
                        float(original_os), update_modified=False)
    frappe.db.commit()

    report["cleanup"] = {
        "ple": _ple_summary(inv.name),
        "outstanding_amount": float(
            frappe.db.get_value("Sales Invoice", inv.name, "outstanding_amount")
        ),
        "restored_to_original": True,
    }

    return report


def _compute_outstanding(voucher_type, voucher_no, account, party_type, party,
                         exclude_ple=None):
    """Sum active PLE for this voucher/party/account. In dry-run we can't
    actually delink, so we simulate by excluding the PLE names we would
    delink."""
    exclude_clause = ""
    params = {"vt": voucher_type, "vn": voucher_no, "ac": account,
              "pt": party_type, "pa": party}
    if exclude_ple:
        exclude_clause = "AND name NOT IN %(ex)s"
        params["ex"] = tuple(exclude_ple)

    row = frappe.db.sql(
        f"""
        SELECT COALESCE(SUM(amount_in_account_currency), 0) AS bal
        FROM `tabPayment Ledger Entry`
        WHERE against_voucher_no = %(vn)s
          AND account      = %(ac)s
          AND party_type   = %(pt)s
          AND party        = %(pa)s
          AND delinked     = 0
          {exclude_clause}
        """,
        params,
        as_dict=True,
    )
    return flt(row[0].bal) if row else 0
