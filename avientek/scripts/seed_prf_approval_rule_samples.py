"""Seed 3 sample PRF Approval Rules for smoke-testing the resolver.

Idempotent — checks by rule_name before insert. Use only on local /
test sites. NOT a patch (won't run on prod migrate).

Rule 1 — "AETPL India Supplier Pay (catch-all)"
    Conditions: company=Avientek Electronics Trading PVT. LTD,
                payment_type=Pay, party_type=Supplier
    Priority: 200 (low — generic catch-all for AETPL)
    Chain:
      L1: User accounts.india1@avientek.com  (no min — always)
      L2: Role  Accounts Manager             (min 50,000 INR)

Rule 2 — "AETPL High-value (>= 500,000 INR)"
    Conditions: company=AETPL, payment_type=Pay,
                amount_from=500000
    Priority: 50 (high — overrides Rule 1 for big-ticket)
    Chain:
      L1: User accounts.india1@avientek.com
      L2: Role  Accounts Manager
      L3: Role  System Manager

Rule 3 — "AVWLL Catch-all"
    Conditions: company=Avientek Trading W.L.L
    Priority: 200
    Chain:
      L1: User accounts@avientek.com
      L2: Role  Accounts Manager
"""
import frappe


_RULES = [
    {
        "rule_name": "AETPL India Supplier Pay (catch-all)",
        "priority": 200,
        "is_active": 1,
        "company": "Avientek Electronics Trading PVT. LTD",
        "payment_type": "Pay",
        "party_type": "Supplier",
        "amount_currency": "INR",
        "chain": [
            {"level": 1, "approver_type": "User", "approver_user": "accounts.india1@avientek.com"},
            {"level": 2, "approver_type": "Role", "approver_role": "Accounts Manager",
             "min_amount_for_level": 50000},
        ],
    },
    {
        "rule_name": "AETPL High-value (>= 500,000 INR)",
        "priority": 50,
        "is_active": 1,
        "company": "Avientek Electronics Trading PVT. LTD",
        "payment_type": "Pay",
        "amount_currency": "INR",
        "amount_from": 500000,
        "chain": [
            {"level": 1, "approver_type": "User", "approver_user": "accounts.india1@avientek.com"},
            {"level": 2, "approver_type": "Role", "approver_role": "Accounts Manager"},
            {"level": 3, "approver_type": "Role", "approver_role": "System Manager"},
        ],
    },
    {
        "rule_name": "AVWLL Catch-all",
        "priority": 200,
        "is_active": 1,
        "company": "Avientek Trading W.L.L",
        "chain": [
            {"level": 1, "approver_type": "User", "approver_user": "accounts@avientek.com"},
            {"level": 2, "approver_type": "Role", "approver_role": "Accounts Manager"},
        ],
    },
]


def execute():
    for spec in _RULES:
        existing = frappe.db.exists("PRF Approval Rule", {"rule_name": spec["rule_name"]})
        if existing:
            # Wipe + re-create to pick up edits to the spec
            frappe.delete_doc("PRF Approval Rule", existing, force=1, ignore_permissions=True)

        chain = spec.pop("chain")
        rule = frappe.get_doc({"doctype": "PRF Approval Rule", **spec})
        for c in chain:
            rule.append("approval_chain", c)
        rule.insert(ignore_permissions=True)
        print(f"  seeded: {rule.name}  '{rule.rule_name}'  pri={rule.priority}  chain={len(rule.approval_chain)}")
    frappe.db.commit()
    print(f"\n[seed_prf_approval_rule_samples] {len(_RULES)} rules seeded.")


if __name__ == "__main__":
    execute()
