"""Smoke for the Quotation Document Approval flow (V3 workflow).

Verifies the post-QAR design (Rahul/Sridhar 2026-05-08):
  - 5 Custom Fields on Quotation (Document Approval section + checkboxes + notes)
  - V3 workflow `Quotation Approval Workflow Avientek (V3)` is_active=1
  - V3 has the expected 9 states
  - V3 has the expected transitions with the dynamic approver role
  - Special-price Property Setters on Quotation Item are allow_on_submit=1
  - validator imports + helpers resolve

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_quotation_document_approval.run
"""
from __future__ import annotations

import frappe


def _hr(t):
    return "\n" + "─" * 70 + f"\n{t}\n" + "─" * 70


_COUNTERS = [0, 0]  # [pass_n, fail_n]


def _check(label, ok, detail=""):
    flag = "OK  " if ok else "FAIL"
    print(f"  {flag}  {label}{(' — ' + detail) if detail else ''}")
    if ok:
        _COUNTERS[0] += 1
    else:
        _COUNTERS[1] += 1
    return ok


def run():
    _COUNTERS[0] = 0
    _COUNTERS[1] = 0
    print("=" * 70)
    print("QUOTATION DOCUMENT APPROVAL (V3) SMOKE")
    print(f"site: {frappe.local.site}")
    print("=" * 70)

    # ── 1. Custom fields on Quotation ──
    print(_hr("[1] Document Approval Custom Fields on Quotation"))
    expected = {
        "custom_document_approval":   {"fieldtype": "Section Break"},
        "custom_request_for_update":  {"fieldtype": "Check"},
        "custom_revision_note":       {"fieldtype": "Small Text",
                                        "mandatory_depends_on": "eval:doc.custom_request_for_update"},
        "custom_cancellation_check":  {"fieldtype": "Check"},
        "custom_cancellation_reason": {"fieldtype": "Small Text",
                                        "mandatory_depends_on": "eval:doc.custom_cancellation_check"},
    }
    meta = frappe.get_meta("Quotation", cached=False)
    fmap = {f.fieldname: f for f in meta.fields}
    for fn, expect in expected.items():
        f = fmap.get(fn)
        if not f:
            _check(f"field {fn!r} present", False, "MISSING")
            continue
        _check(f"field {fn!r} present", True, f.fieldtype)
        for k, v in expect.items():
            actual = getattr(f, k, None)
            ok = (actual or "") == v
            _check(f"  {fn}.{k} = {v!r}", ok, f"got {actual!r}")

    # ── 2. V3 Workflow exists and active ──
    print(_hr("[2] Quotation Approval Workflow Avientek (V3)"))
    WF = "Quotation Approval Workflow Avientek (V3)"
    exists = frappe.db.exists("Workflow", WF)
    _check("workflow exists", bool(exists))
    if not exists:
        print("  Cannot continue without workflow.")
        return {"pass": _COUNTERS[0], "fail": _COUNTERS[1]}

    wf = frappe.get_doc("Workflow", WF)
    _check("is_active=1", wf.is_active == 1, f"is_active={wf.is_active}")
    _check("document_type=Quotation",
                     wf.document_type == "Quotation",
                     wf.document_type)
    expected_states = {
        "Draft", "Submitted", "Requested for update", "Approved for Update",
        "Pending For Approval", "Approved", "Sent for Revision",
        "Cancellation Requested", "Cancelled",
    }
    have_states = {s.state for s in wf.states}
    missing = expected_states - have_states
    _check("all 9 V3 states present",
                     not missing,
                     f"missing={sorted(missing)}" if missing else "")

    # No other Quotation workflow is active simultaneously
    other_active = frappe.db.sql(
        """SELECT name FROM `tabWorkflow`
           WHERE document_type='Quotation' AND is_active=1 AND name != %s""",
        (WF,),
    )
    _check("V3 is the ONLY active Quotation workflow",
                     not other_active,
                     f"others active: {[r[0] for r in other_active]}" if other_active else "")

    # ── 3. Transitions reference the dynamic approver roles ──
    print(_hr("[3] V3 transitions reference dynamic approver roles"))
    from avientek.api.quotation_high_probability import _settings_roles
    cfg = _settings_roles()
    approver_roles = cfg.get("approver_roles") or (cfg.get("approver_role"),)
    creator_roles = cfg.get("creator_roles") or (cfg.get("creator_role"),)
    approver = approver_roles[0] if approver_roles else None
    creator = creator_roles[0] if creator_roles else None
    _check("approver_roles resolved", bool(approver), f"={list(approver_roles)!r}")
    _check("creator_roles resolved", bool(creator), f"={list(creator_roles)!r}")

    # Find at least one transition each — case-insensitive lookup since
    # Frappe normalizes role-link writes to whatever case the role
    # record physically uses in the DB (so 'Sales support L2' might be
    # stored as 'Sales Support L2' if that's the existing record).
    txns_by_role_lower = {}
    for t in wf.transitions:
        if t.allowed:
            txns_by_role_lower.setdefault(
                (t.allowed or "").lower(), []).append(
                    f"{t.state} -[{t.action}]-> {t.next_state}"
                )
    approver_l = (approver or "").lower()
    creator_l = (creator or "").lower()
    _check(f"approver role {approver!r} used in transitions (case-insensitive)",
                     approver_l in txns_by_role_lower,
                     f"used in {len(txns_by_role_lower.get(approver_l, []))} transitions")
    _check(f"creator role {creator!r} used in transitions (case-insensitive)",
                     creator_l in txns_by_role_lower,
                     f"used in {len(txns_by_role_lower.get(creator_l, []))} transitions")

    # No self-approval on the approver-role transitions
    self_approve_violators = [
        f"{t.state} -[{t.action}]-> {t.next_state}"
        for t in wf.transitions
        if (t.allowed or "").lower() == approver_l and t.allow_self_approval == 1
    ]
    _check("no self-approval on approver transitions",
                     not self_approve_violators,
                     f"violators: {self_approve_violators}" if self_approve_violators else "")

    # ── 4. Property Setters for special prices on Quotation Item ──
    print(_hr("[4] Special-price Property Setters on Quotation Item"))
    for fn in ("custom_special_price", "custom_special_rate",
               "custom_special_price_note", "custom_addl_discount_amount"):
        ps_name = f"Quotation Item-{fn}-allow_on_submit"
        val = frappe.db.get_value("Property Setter", ps_name, "value")
        _check(f"PS {ps_name!r} value=1",
                         val in ("1", 1, True),
                         f"value={val!r}")

    # ── 5. Validator helpers exist + import cleanly ──
    print(_hr("[5] Validator + helpers"))
    try:
        from avientek.api.quotation_high_probability import (
            before_save, before_cancel, on_update_after_submit,
            notify_probability_100, _changed_only_special_prices,
            _settings_roles, SPECIAL_PRICE_FIELDS,
        )
        _check("validator + notification + helpers importable", True)
        _check("SPECIAL_PRICE_FIELDS has 4 entries",
                         len(SPECIAL_PRICE_FIELDS) == 4,
                         f"got {len(SPECIAL_PRICE_FIELDS)}")
    except Exception as e:
        _check("validator + helpers importable", False, repr(e))

    # ── 6. QAR remnants are gone ──
    print(_hr("[6] QAR removal verified"))
    _check("DocType 'Quotation Action Request' removed",
                     not frappe.db.exists("DocType", "Quotation Action Request"))
    _check("Workflow 'Quotation Action Request Approval' removed",
                     not frappe.db.exists("Workflow", "Quotation Action Request Approval"))

    # Verdict
    pass_n, fail_n = _COUNTERS
    total = pass_n + fail_n
    print("\n" + "=" * 70)
    if fail_n == 0:
        print(f"  ✅  ALL {total} CHECKS PASSED — Document Approval V3 wired")
    else:
        print(f"  ❌  {fail_n}/{total} FAILED")
    print("=" * 70)
    return {"pass": pass_n, "fail": fail_n, "total": total}
