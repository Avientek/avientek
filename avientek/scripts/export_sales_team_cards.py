"""Read the 6 Quotation Number Cards from the DB and write them as
on-disk fixtures so they ship with the avientek app.

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.export_sales_team_cards.run
"""
import json
import os

import frappe


CARD_NAMES = [
    "Pending Level 2 Approvals",
    "Pending Level 1 Approvals",
    "Approved Quotes",
    "My Quotes Pending Approval",
    "My Draft Quotations",
    "My Rejected Quotations",
]


def _slug(name):
    return name.lower().replace(" ", "_").replace("-", "_")


def run():
    base = frappe.get_app_path("avientek", "avientek", "number_card")
    print(f"writing into {base}")
    found = []
    missing = []
    for name in CARD_NAMES:
        if not frappe.db.exists("Number Card", name):
            missing.append(name)
            continue
        d = frappe.get_doc("Number Card", name).as_dict(no_default_fields=True,
                                                        no_nulls=True)
        # Strip volatile / per-site fields
        for k in ("creation", "modified", "modified_by", "owner",
                   "_assign", "_user_tags", "_comments", "_liked_by"):
            d.pop(k, None)
        d["is_standard"] = 1
        d["module"] = "Avientek"
        d["doctype"] = "Number Card"

        slug = _slug(name)
        out_dir = os.path.join(base, slug)
        os.makedirs(out_dir, exist_ok=True)
        # Frappe expects an __init__.py + the JSON named after the slug
        init_p = os.path.join(out_dir, "__init__.py")
        if not os.path.exists(init_p):
            with open(init_p, "w") as fh:
                fh.write("")
        json_p = os.path.join(out_dir, f"{slug}.json")
        with open(json_p, "w") as fh:
            json.dump(d, fh, indent=1, ensure_ascii=False, default=str)
            fh.write("\n")
        found.append((name, json_p))

    print("\nWritten:")
    for name, path in found:
        print(f"  ✓ {name:35s} -> {path}")
    if missing:
        print("\nMissing on this site:")
        for name in missing:
            print(f"  ✗ {name}")
    return {"found": [n for n, _ in found], "missing": missing}
