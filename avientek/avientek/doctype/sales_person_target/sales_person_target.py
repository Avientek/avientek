# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt

"""Sales Person Target — per-sales-person, per-fiscal-year target matrix.

Matrix dimensions per row (`Sales Person Target Detail`):
    month        — required
    item_group   — optional, empty = all
    brand        — optional, empty = all
    territory    — optional
    country      — optional

Three target amounts per row (Currency, in the parent's `currency`):
    target_booking, target_billing, target_margin

Rollup:
    direct totals → sum of `targets` rows
    descendant totals → sum of submitted Sales Person Target docs whose
        sales_person is a descendant of this doc's sales_person in the
        Sales Person tree (parent_sales_person), for the same fiscal year

Used downstream by the (future) "Sales Person Target vs Actual" report.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class SalesPersonTarget(Document):
    def validate(self):
        self._validate_unique_sp_fiscal_year()
        self._compute_direct_totals()
        self._compute_descendant_totals()

    def on_submit(self):
        # Re-walk descendants of this SP's *parent* so the parent's
        # rollup picks up this newly-submitted child.
        self._refresh_ancestor_rollups()

    def on_cancel(self):
        self._refresh_ancestor_rollups()

    # ── validation helpers ────────────────────────────────────────────

    def _validate_unique_sp_fiscal_year(self):
        if not (self.sales_person and self.fiscal_year):
            return
        existing = frappe.db.sql(
            """SELECT name FROM `tabSales Person Target`
               WHERE sales_person = %s
                 AND fiscal_year = %s
                 AND docstatus < 2
                 AND name != %s""",
            (self.sales_person, self.fiscal_year, self.name or ""),
            pluck="name",
        )
        if existing:
            frappe.throw(
                _("Sales Person Target {0} already exists for {1} / {2}. "
                  "Cancel and amend the existing one instead.").format(
                    existing[0], self.sales_person, self.fiscal_year
                )
            )

    # ── rollup ────────────────────────────────────────────────────────

    def _compute_direct_totals(self):
        booking = sum(flt(r.target_booking) for r in (self.targets or []))
        billing = sum(flt(r.target_billing) for r in (self.targets or []))
        margin = sum(flt(r.target_margin) for r in (self.targets or []))
        self.total_target_booking = booking
        self.total_target_billing = billing
        self.total_target_margin = margin

    def _compute_descendant_totals(self):
        if not (self.sales_person and self.fiscal_year):
            self.descendant_target_booking = 0
            self.descendant_target_billing = 0
            self.descendant_target_margin = 0
            return
        descendant_sps = _get_descendant_sales_persons(self.sales_person)
        if not descendant_sps:
            self.descendant_target_booking = 0
            self.descendant_target_billing = 0
            self.descendant_target_margin = 0
            return
        ph = ", ".join(["%s"] * len(descendant_sps))
        row = frappe.db.sql(
            f"""SELECT
                  COALESCE(SUM(total_target_booking), 0) AS bk,
                  COALESCE(SUM(total_target_billing), 0) AS bl,
                  COALESCE(SUM(total_target_margin),  0) AS mg
                FROM `tabSales Person Target`
                WHERE docstatus = 1
                  AND fiscal_year = %s
                  AND sales_person IN ({ph})""",
            [self.fiscal_year] + descendant_sps,
            as_dict=True,
        )
        self.descendant_target_booking = flt(row[0].bk) if row else 0
        self.descendant_target_billing = flt(row[0].bl) if row else 0
        self.descendant_target_margin = flt(row[0].mg) if row else 0

    def _refresh_ancestor_rollups(self):
        """Re-validate any submitted ancestor SPT for the same fiscal year
        so its descendant totals reflect this submit/cancel. Cheap — only
        reads + db_set, no full save."""
        if not (self.sales_person and self.fiscal_year):
            return
        ancestors = _get_ancestor_sales_persons(self.sales_person)
        if not ancestors:
            return
        ph = ", ".join(["%s"] * len(ancestors))
        ancestor_spts = frappe.db.sql(
            f"""SELECT name, sales_person FROM `tabSales Person Target`
                WHERE docstatus = 1
                  AND fiscal_year = %s
                  AND sales_person IN ({ph})""",
            [self.fiscal_year] + ancestors,
            as_dict=True,
        )
        for r in ancestor_spts:
            try:
                doc = frappe.get_doc("Sales Person Target", r.name)
                doc._compute_descendant_totals()
                # Use db_set to avoid re-running submit/cancel hooks recursively
                for fn in (
                    "descendant_target_booking",
                    "descendant_target_billing",
                    "descendant_target_margin",
                ):
                    frappe.db.set_value(
                        "Sales Person Target", doc.name, fn, doc.get(fn),
                        update_modified=False,
                    )
            except Exception:
                frappe.log_error(
                    title=f"SPT ancestor rollup refresh failed for {r.name}",
                    message=frappe.get_traceback(),
                )


# ── module-level helpers ──────────────────────────────────────────────

def _get_descendant_sales_persons(sp_name):
    """All descendants of sp_name in the Sales Person tree (excluding
    itself), via parent_sales_person edges."""
    descendants = []
    frontier = [sp_name]
    seen = {sp_name}
    while frontier:
        ph = ", ".join(["%s"] * len(frontier))
        rows = frappe.db.sql(
            f"""SELECT name FROM `tabSales Person`
                WHERE parent_sales_person IN ({ph})
                  AND IFNULL(enabled, 1) = 1""",
            frontier,
            pluck="name",
        )
        new_rows = [r for r in rows if r not in seen]
        descendants.extend(new_rows)
        seen.update(new_rows)
        frontier = new_rows
    return descendants


def _get_ancestor_sales_persons(sp_name):
    """Walk parent_sales_person chain upward. Returns ancestors only
    (not sp_name itself). Bounded depth 25 as a safety fuse against
    self-referential cycles."""
    ancestors = []
    cursor = sp_name
    seen = {sp_name}
    for _ in range(25):
        parent = frappe.db.get_value("Sales Person", cursor, "parent_sales_person")
        if not parent or parent in seen or parent == "All Sales Persons":
            break
        ancestors.append(parent)
        seen.add(parent)
        cursor = parent
    return ancestors


# ── whitelisted: copy from previous year ──────────────────────────────

@frappe.whitelist()
def copy_from_previous_year(sales_person, fiscal_year, source_fiscal_year=None):
    """Create a fresh draft Sales Person Target for (sales_person, fiscal_year)
    pre-populated from the most recent submitted SPT for the same sales person.

    If `source_fiscal_year` is omitted, picks the most recent submitted
    SPT for this sales person regardless of year.

    Returns the new document name. Caller (JS) navigates to it.
    """
    if not sales_person or not fiscal_year:
        frappe.throw(_("sales_person and fiscal_year are required"))

    if frappe.db.exists(
        "Sales Person Target",
        {"sales_person": sales_person, "fiscal_year": fiscal_year, "docstatus": ["<", 2]},
    ):
        frappe.throw(_(
            "A Sales Person Target already exists for {0} in {1}."
        ).format(sales_person, fiscal_year))

    where = ["docstatus = 1", "sales_person = %s"]
    args = [sales_person]
    if source_fiscal_year:
        where.append("fiscal_year = %s")
        args.append(source_fiscal_year)

    src_name = frappe.db.sql(
        f"""SELECT name FROM `tabSales Person Target`
            WHERE {' AND '.join(where)}
            ORDER BY modified DESC LIMIT 1""",
        args, pluck="name",
    )
    if not src_name:
        frappe.throw(_("No submitted source target found to copy from."))

    src = frappe.get_doc("Sales Person Target", src_name[0])
    new = frappe.new_doc("Sales Person Target")
    new.sales_person = sales_person
    new.fiscal_year = fiscal_year
    new.company = src.company
    new.currency = src.currency
    new.include_descendant_targets = src.include_descendant_targets
    new.notes = src.notes
    for r in (src.targets or []):
        new.append("targets", {
            "month": r.month,
            "item_group": r.item_group,
            "brand": r.brand,
            "territory": r.territory,
            "country": r.country,
            "target_booking": flt(r.target_booking),
            "target_billing": flt(r.target_billing),
            "target_margin": flt(r.target_margin),
        })
    new.flags.ignore_permissions = False
    new.insert()
    return new.name
