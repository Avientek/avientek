"""Smoke test for the PRF Approval Rule engine — runs against REAL PRFs
on the local bench. Read-only against PRFs (uses doc-in-memory mutation,
never saves).

Run:  bench --site avientekv21.local execute \
        avientek.scripts.smoke_prf_approval_engine.execute

What it checks:
  Test 1  Resolver returns None for any PRF when ALL rules disabled
  Test 2  AETPL low-amount Supplier Pay → matches Rule 1 (catch-all,
          single-level L1 only since amount < 50k)
  Test 3  AETPL >= 50,000 INR → Rule 1 picks up L2 (Accounts Manager)
  Test 4  AETPL >= 500,000 INR → Rule 2 wins (priority 50 beats 200),
          3-level chain
  Test 5  Wrong-company PRF (AVWLL) → Rule 3 wins, Rule 1+2 don't match
  Test 6  Receive-type PRF → no rule matches (none allow Receive)
  Test 7  Date validity: rule with valid_to=yesterday doesn't match
  Test 8  Self-approval skip: PRF owner = L1 approver → L1 dropped,
          L2 promoted to position 1

PRF reference docs used (read-only): AVLTD-01606 (AETPL Pay 9,119 INR),
AVWLL-00363 (AVWLL Pay).
"""
import json
import frappe
from frappe.utils import getdate, add_days
from avientek.events.payment_request_form import (
    resolve_approval_chain,
    _find_matching_rule,
    _build_chain,
)


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def _assert(name, cond, detail=""):
    print(f"  [{PASS if cond else FAIL}] {name}{(' — ' + detail) if detail else ''}")
    return bool(cond)


def execute():
    print("=" * 70)
    print("PRF Approval Rule engine — smoke test")
    print("=" * 70)

    results = []

    # Re-seed before each run so tests are deterministic
    from avientek.scripts.seed_prf_approval_rule_samples import execute as seed
    seed()
    print()

    # ── Test 1: All rules disabled → no match ──
    print("Test 1: All rules disabled → resolver returns None")
    rule_names = [r.name for r in frappe.get_all("PRF Approval Rule")]
    frappe.db.set_value("PRF Approval Rule", {"name": ["in", rule_names]}, "is_active", 0)
    frappe.db.commit()
    doc = frappe.get_doc("Payment Request Form", "AVLTD-01606")
    doc.custom_approval_rule = None
    resolve_approval_chain(doc)
    results.append(_assert("custom_approval_rule is None", doc.custom_approval_rule is None,
                           f"got={doc.custom_approval_rule}"))
    results.append(_assert("custom_current_approval_level == 0",
                           int(doc.custom_current_approval_level or 0) == 0))
    # Restore active flag
    frappe.db.set_value("PRF Approval Rule", {"name": ["in", rule_names]}, "is_active", 1)
    frappe.db.commit()
    print()

    # ── Test 2: AETPL low amount (9,119 INR) → Rule 1, L1 only ──
    print("Test 2: AETPL Supplier Pay 9,119 INR → Rule 1 wins, L2 skipped (min 50k)")
    doc = frappe.get_doc("Payment Request Form", "AVLTD-01606")
    doc.owner = "Administrator"  # non-approver — avoid Test 8 self-skip interference
    doc.total_outstanding_amount = 9119
    resolve_approval_chain(doc)
    chain = json.loads(doc.custom_approval_chain or "[]")
    rule_name = frappe.db.get_value("PRF Approval Rule",
                                     doc.custom_approval_rule, "rule_name") if doc.custom_approval_rule else None
    results.append(_assert("matched rule = AETPL catch-all",
                           rule_name == "AETPL India Supplier Pay (catch-all)",
                           f"got={rule_name}"))
    results.append(_assert("chain has 1 level (L2 skipped by min_amount)",
                           len(chain) == 1, f"len={len(chain)}"))
    results.append(_assert("L1 = accounts.india1@avientek.com",
                           chain[0]["user"] == "accounts.india1@avientek.com" if chain else False))
    print()

    # ── Test 3: AETPL 75,000 INR → Rule 1, both L1 + L2 ──
    print("Test 3: AETPL Supplier Pay 75,000 INR → Rule 1, full 2-level chain")
    doc = frappe.get_doc("Payment Request Form", "AVLTD-01606")
    doc.owner = "Administrator"  # non-approver — avoid Test 8 self-skip interference
    doc.total_outstanding_amount = 75000
    resolve_approval_chain(doc)
    chain = json.loads(doc.custom_approval_chain or "[]")
    results.append(_assert("chain has 2 levels", len(chain) == 2, f"len={len(chain)}"))
    results.append(_assert("L2 is Role = Accounts Manager",
                           len(chain) >= 2 and chain[1].get("type") == "Role"
                           and chain[1].get("role") == "Accounts Manager"))
    print()

    # ── Test 4: AETPL 750,000 INR → Rule 2 wins (priority 50) ──
    print("Test 4: AETPL Supplier Pay 750,000 INR → Rule 2 wins (priority 50 < 200)")
    doc = frappe.get_doc("Payment Request Form", "AVLTD-01606")
    doc.owner = "Administrator"  # non-approver — avoid Test 8 self-skip interference
    doc.total_outstanding_amount = 750000
    resolve_approval_chain(doc)
    chain = json.loads(doc.custom_approval_chain or "[]")
    rule_name = frappe.db.get_value("PRF Approval Rule",
                                     doc.custom_approval_rule, "rule_name") if doc.custom_approval_rule else None
    results.append(_assert("Rule 2 wins by priority",
                           rule_name == "AETPL High-value (>= 500,000 INR)",
                           f"got={rule_name}"))
    results.append(_assert("3-level chain", len(chain) == 3, f"len={len(chain)}"))
    print()

    # ── Test 5: AVWLL PRF → Rule 3 wins (different company) ──
    print("Test 5: AVWLL PRF → Rule 3 wins, AETPL rules don't match")
    avwll_prfs = frappe.get_all("Payment Request Form",
                                filters={"company": "Avientek Trading W.L.L"},
                                fields=["name"], limit_page_length=1)
    if avwll_prfs:
        doc = frappe.get_doc("Payment Request Form", avwll_prfs[0].name)
        # Force a known amount so Rule 2's amount band doesn't accidentally trigger
        doc.total_outstanding_amount = 1000
        resolve_approval_chain(doc)
        rule_name = frappe.db.get_value("PRF Approval Rule",
                                         doc.custom_approval_rule, "rule_name") if doc.custom_approval_rule else None
        results.append(_assert("Rule 3 (AVWLL catch-all) wins",
                               rule_name == "AVWLL Catch-all", f"got={rule_name}"))
    else:
        results.append(_assert("AVWLL PRF found", False, "no AVWLL PRF available — skipped"))
    print()

    # ── Test 6: Receive-type PRF → no rule matches ──
    print("Test 6: Receive-type PRF → no rule matches (all rules are Pay or any)")
    doc = frappe.get_doc("Payment Request Form", "AVLTD-01606")
    doc.payment_type = "Receive"
    doc.total_outstanding_amount = 10000
    resolve_approval_chain(doc)
    results.append(_assert("no rule matched",
                           not doc.custom_approval_rule,
                           f"got={doc.custom_approval_rule}"))
    print()

    # ── Test 7: Date validity — rule expired yesterday ──
    print("Test 7: Rule with valid_to=yesterday → does not match")
    expired_name = frappe.db.get_value("PRF Approval Rule",
                                        {"rule_name": "AETPL India Supplier Pay (catch-all)"})
    yesterday = add_days(getdate(), -1)
    frappe.db.set_value("PRF Approval Rule", expired_name, "valid_to", yesterday)
    # Also expire Rule 2 so we test catch-all rule's expiry
    rule2 = frappe.db.get_value("PRF Approval Rule",
                                 {"rule_name": "AETPL High-value (>= 500,000 INR)"})
    frappe.db.set_value("PRF Approval Rule", rule2, "valid_to", yesterday)
    frappe.db.commit()

    doc = frappe.get_doc("Payment Request Form", "AVLTD-01606")
    doc.payment_type = "Pay"
    doc.total_outstanding_amount = 9119
    resolve_approval_chain(doc)
    results.append(_assert("expired rule didn't match (AETPL)",
                           not doc.custom_approval_rule,
                           f"got={doc.custom_approval_rule}"))
    # Restore
    frappe.db.set_value("PRF Approval Rule", expired_name, "valid_to", None)
    frappe.db.set_value("PRF Approval Rule", rule2, "valid_to", None)
    frappe.db.commit()
    print()

    # ── Test 8: Self-approval skip ──
    print("Test 8: PRF owner == L1 approver → L1 dropped, chain renumbered")
    rule1 = frappe.get_doc("PRF Approval Rule", expired_name)
    rule1.approval_chain[0].approver_user = "accounts.india1@avientek.com"
    rule1.save(ignore_permissions=True)
    frappe.db.commit()

    doc = frappe.get_doc("Payment Request Form", "AVLTD-01606")
    # Owner is already accounts.india1@avientek.com — see Test 0 below
    doc.total_outstanding_amount = 75000  # so L2 kicks in too
    resolve_approval_chain(doc)
    chain = json.loads(doc.custom_approval_chain or "[]")
    results.append(_assert("self-approval skipped",
                           len(chain) == 1 and chain[0].get("type") == "Role"
                           and chain[0]["level"] == 1,
                           f"chain={chain}"))
    print()

    # ── Test 9: Dynamic on_empty_chain = 'Auto-Approve' ──
    print("Test 9: on_empty_chain = Auto-Approve → rule stamped, empty chain, level=0")
    rule3 = frappe.db.get_value("PRF Approval Rule", {"rule_name": "AVWLL Catch-all"})
    # AVWLL rule's L1 user = accounts@avientek.com. Force PRF owner to that
    # so L1 self-skips, and L2 too (no min_amount), but wait — L2 is Role,
    # not User, so self-skip doesn't apply. To make L2 also skip, we set
    # min_amount_for_level high.
    r3 = frappe.get_doc("PRF Approval Rule", rule3)
    r3.approval_chain[1].min_amount_for_level = 999999  # force L2 skip
    r3.save(ignore_permissions=True)
    frappe.db.commit()

    avwll_prfs = frappe.get_all("Payment Request Form",
                                 filters={"company": "Avientek Trading W.L.L"},
                                 fields=["name"], limit_page_length=1)
    if avwll_prfs:
        doc = frappe.get_doc("Payment Request Form", avwll_prfs[0].name)
        doc.owner = "accounts@avientek.com"  # == L1 → self-skip → empty chain
        doc.total_outstanding_amount = 100
        resolve_approval_chain(doc)
        rule_name = frappe.db.get_value("PRF Approval Rule",
                                         doc.custom_approval_rule, "rule_name") if doc.custom_approval_rule else None
        results.append(_assert("rule stamped (Auto-Approve policy)",
                               rule_name == "AVWLL Catch-all", f"got={rule_name}"))
        results.append(_assert("chain is empty []",
                               json.loads(doc.custom_approval_chain or "[]") == []))
        results.append(_assert("current_level == 0 (auto-approved)",
                               int(doc.custom_current_approval_level or 0) == 0))
    # Restore
    r3 = frappe.get_doc("PRF Approval Rule", rule3)
    r3.approval_chain[1].min_amount_for_level = 0
    r3.save(ignore_permissions=True)
    frappe.db.commit()
    print()

    # ── Test 10: Dynamic on_empty_chain = 'Throw Error' ──
    print("Test 10: on_empty_chain = Throw Error → frappe.throw raised")
    rule2_name = frappe.db.get_value("PRF Approval Rule",
                                       {"rule_name": "AETPL High-value (>= 500,000 INR)"})
    # Force collapse: set every level's approver_user to the PRF owner
    # AND uncheck allow_self_approval. Then verify throws.
    r2 = frappe.get_doc("PRF Approval Rule", rule2_name)
    r2.allow_self_approval = 0
    for row in r2.approval_chain:
        row.approver_type = "User"
        row.approver_user = "accounts.india1@avientek.com"
    r2.save(ignore_permissions=True)
    frappe.db.commit()

    doc = frappe.get_doc("Payment Request Form", "AVLTD-01606")
    doc.owner = "accounts.india1@avientek.com"
    doc.total_outstanding_amount = 750000  # forces Rule 2 (priority 50)
    threw = False
    try:
        resolve_approval_chain(doc)
    except frappe.ValidationError:
        threw = True
    except Exception as e:
        # frappe.throw may raise different exception types — accept any
        threw = "empty" in str(e).lower() or "chain" in str(e).lower()
    results.append(_assert("Throw Error policy raised exception", threw))
    print()

    # ── Test 11: Dynamic allow_self_approval = 1 ──
    print("Test 11: allow_self_approval=1 → owner CAN be in own chain")
    # Reset Rule 2 to a clean state
    r2 = frappe.get_doc("PRF Approval Rule", rule2_name)
    r2.allow_self_approval = 1  # ← the dynamic toggle
    # L1 = User accounts.india1, L2 = Role, L3 = Role
    r2.approval_chain[0].approver_type = "User"
    r2.approval_chain[0].approver_user = "accounts.india1@avientek.com"
    r2.approval_chain[1].approver_type = "Role"
    r2.approval_chain[1].approver_role = "Accounts Manager"
    r2.approval_chain[2].approver_type = "Role"
    r2.approval_chain[2].approver_role = "System Manager"
    r2.save(ignore_permissions=True)
    frappe.db.commit()

    doc = frappe.get_doc("Payment Request Form", "AVLTD-01606")
    doc.owner = "accounts.india1@avientek.com"  # SAME as L1 user
    doc.total_outstanding_amount = 750000
    resolve_approval_chain(doc)
    chain = json.loads(doc.custom_approval_chain or "[]")
    results.append(_assert("L1 NOT skipped despite owner==L1.user",
                           len(chain) == 3 and chain[0].get("user") == "accounts.india1@avientek.com",
                           f"chain_len={len(chain)} first_user={chain[0].get('user') if chain else '-'}"))
    print()

    # ── Summary ──
    print("=" * 70)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"SMOKE RESULT: {passed}/{total} assertions passed")
    print("=" * 70)
    if passed != total:
        raise AssertionError(f"{total - passed} assertion(s) failed")
