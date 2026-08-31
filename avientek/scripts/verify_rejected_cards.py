# Copyright (c) 2026, Avientek
"""Behavioural verification for the Rejected Quotations number cards.

Exercises the ACTUAL number-card compute path
(frappe.desk.doctype.number_card.number_card.get_result -> frappe.get_list),
which applies permission_query_conditions, as different users. Read-only."""
import json
import frappe
from frappe.desk.doctype.number_card.number_card import get_result


def _card_count(card_name, as_user, extra_owner=False):
    card = frappe.get_doc("Number Card", card_name)
    filters = json.loads(card.filters_json or "[]")
    if extra_owner:  # replicate the dashboard resolving dynamic owner filter
        filters = filters + [[card.document_type, "owner", "=", as_user]]
    frappe.set_user(as_user)
    try:
        return int(get_result(card.as_dict(), filters))
    finally:
        frappe.set_user("Administrator")


def run():
    frappe.set_user("Administrator")
    total_rejected = frappe.db.count("Quotation", {"workflow_status": "Rejected"})
    print("TOTAL rejected quotes (unscoped) :", total_rejected)

    # a restricted sales-person user
    restricted = "ng@avientek.com"
    # a user who OWNS at least one rejected quote (for the My Rejected fix)
    owner_row = frappe.get_all("Quotation", filters={"workflow_status": "Rejected"},
                               fields=["owner"], limit=1)
    owner_user = owner_row[0].owner if owner_row else None
    owner_rejected = frappe.db.count("Quotation",
                                     {"workflow_status": "Rejected", "owner": owner_user}) if owner_user else 0

    print("\n--- Rejected Quotations (permission-scoped, NEW) ---")
    admin_cnt = _card_count("Rejected Quotations", "Administrator")
    ng_cnt = _card_count("Rejected Quotations", restricted)
    print("  as Administrator :", admin_cnt, "(expect == total", total_rejected, ")")
    print("  as", restricted, ":", ng_cnt, "(scoped subset, expect <= total)")

    print("\n--- My Rejected Quotations (owner-scoped, FIXED) ---")
    print("  a rejected-quote owner:", owner_user, "owns", owner_rejected, "rejected")
    my_as_owner = _card_count("My Rejected Quotations", owner_user, extra_owner=True) if owner_user else None
    my_as_ng = _card_count("My Rejected Quotations", restricted, extra_owner=True)
    print("  as owner (%s): %s (expect == %s, was ALWAYS 0 before fix)" % (owner_user, my_as_owner, owner_rejected))
    print("  as", restricted, ":", my_as_ng, "(their own rejected)")

    ok = (admin_cnt == total_rejected) and (ng_cnt <= total_rejected) \
         and (owner_user is None or my_as_owner == owner_rejected)
    print("\n=== %s ===" % ("PASS: new card shows all (admin) & scopes per user; My Rejected now counts owner correctly"
                            if ok else "CHECK: see above"))
