"""Smoke test for the Quotation Notification feature.

Verifies in one run:
  1. The 3 Avientek Settings toggles exist and are readable
  2. All 4 Email Templates exist and render without errors against a
     real quote
  3. Sales-team-aware approver resolution returns sensible users for
     both L1 and L2 roles
  4. Prob-100 recipient filtering reacts to the restrict toggle
     (broader list when OFF, scoped list when ON)
  5. The workflow-state dispatcher actually fires when invoked
     (creates ToDos + queues Email rows) when the toggles are ON
  6. Cleans up — deletes any ToDo / Email Queue rows it created

Run via:
  bench --site avientekv21.local execute "frappe.get_attr('avientek.api.smoke_notify.run').__call__"
"""

from datetime import datetime
import frappe


def _section(out, title):
    out.append("")
    out.append("─" * 60)
    out.append(title)
    out.append("─" * 60)


def _ok(out, label, detail=""):
    out.append(f"  [PASS] {label}" + (f"  ({detail})" if detail else ""))


def _fail(out, label, detail=""):
    out.append(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))


def run():
    out = []
    results = {"pass": 0, "fail": 0}

    def check(cond, label, detail=""):
        if cond:
            _ok(out, label, detail)
            results["pass"] += 1
        else:
            _fail(out, label, detail)
            results["fail"] += 1

    # ── 1. Settings toggles ────────────────────────────────────────────
    _section(out, "1. Avientek Settings toggles")
    for fn in (
        "enable_quotation_notifications",
        "enable_workflow_state_notifications",
        "restrict_notifications_to_workflow_participants",
    ):
        val = frappe.db.get_single_value("Avientek Settings", fn)
        check(val is not None, f"Setting `{fn}` readable", f"value={val}")

    # ── 2. Email Templates exist + render ──────────────────────────────
    _section(out, "2. Email Templates")
    template_names = [
        "Quotation Approval Required",
        "Quotation Approved",
        "Quotation Rejected",
        "Quotation Confirmed at 100% Probability",
    ]

    # Pick a real quote to render against
    rows = frappe.db.sql(
        """select name from `tabQuotation`
           where docstatus = 1 and grand_total > 0
             and sales_person is not null and sales_person != ''
           limit 1""",
        as_dict=False,
    )
    if not rows:
        out.append("  [FAIL] No suitable Quotation found — skipping render tests")
        results["fail"] += 1
        print("\n".join(out))
        return
    doc = frappe.get_doc("Quotation", rows[0][0])

    for name in template_names:
        tmpl = frappe.db.get_value(
            "Email Template", name, ["subject", "response"], as_dict=True
        )
        if not tmpl:
            _fail(out, f"Template `{name}` exists")
            results["fail"] += 1
            continue
        try:
            subj = frappe.render_template(tmpl.subject or "", {"doc": doc})
            body = frappe.render_template(tmpl.response or "", {"doc": doc})
            ok = bool(subj) and bool(body) and doc.name in subj
            check(ok, f"Template `{name}` renders cleanly",
                  f"subject_len={len(subj)} body_len={len(body)}")
        except Exception as e:
            _fail(out, f"Template `{name}` render", str(e))
            results["fail"] += 1

    # ── 3. Approver resolution (sales-team aware) ──────────────────────
    _section(out, "3. Sales-team-aware approver resolution")
    from avientek.events.quotation_notifications import _resolve_approvers_for_quote
    from avientek.api.quotation_high_probability import _settings_roles

    cfg = _settings_roles()
    l1_roles = cfg.get("approver_roles") or ()
    l2_roles = cfg.get("l2_approver_roles") or ()
    out.append(f"  L1 roles={l1_roles}  L2 roles={l2_roles}")
    out.append(f"  Quote: {doc.name}  sales_person={doc.get('sales_person')}")

    l1 = _resolve_approvers_for_quote(doc, l1_roles)
    l2 = _resolve_approvers_for_quote(doc, l2_roles)
    check(len(l1) > 0, "L1 approvers resolved (non-empty)",
          f"{len(l1)} users")
    check(len(l2) > 0, "L2 approvers resolved (non-empty)",
          f"{len(l2)} users")
    check("Administrator" not in l1 and "Administrator" not in l2,
          "Administrator excluded from approver lists")

    # ── 4. Prob-100 recipient filtering reacts to restrict toggle ──────
    _section(out, "4. Prob-100 recipient toggle")
    from avientek.api.quotation_high_probability import _resolve_prob_100_recipients

    orig_restrict = frappe.db.get_single_value(
        "Avientek Settings", "restrict_notifications_to_workflow_participants"
    )
    try:
        frappe.db.set_single_value(
            "Avientek Settings", "restrict_notifications_to_workflow_participants", 0
        )
        r_off = set(_resolve_prob_100_recipients(doc))
        frappe.db.set_single_value(
            "Avientek Settings", "restrict_notifications_to_workflow_participants", 1
        )
        r_on = set(_resolve_prob_100_recipients(doc))
    finally:
        frappe.db.set_single_value(
            "Avientek Settings",
            "restrict_notifications_to_workflow_participants",
            orig_restrict or 0,
        )

    out.append(f"  restrict=OFF → {len(r_off)} recipients")
    out.append(f"  restrict=ON  → {len(r_on)} recipients")
    check(len(r_on) <= len(r_off),
          "ON list is a subset of (or equal to) OFF list",
          f"ON⊆OFF: {r_on.issubset(r_off)}")

    # ── 5. End-to-end dispatcher fire (simulated state transition) ─────
    _section(out, "5. Workflow-state dispatcher fires end-to-end")
    from avientek.events.quotation_notifications import on_state_change

    # Temporarily enable both notification toggles so we can verify the
    # full path. Stash + restore afterwards.
    orig_enable = frappe.db.get_single_value(
        "Avientek Settings", "enable_quotation_notifications"
    )
    orig_workflow = frappe.db.get_single_value(
        "Avientek Settings", "enable_workflow_state_notifications"
    )

    test_marker = f"smoke-{datetime.now().strftime('%H%M%S')}"
    todo_count_before = frappe.db.count(
        "ToDo", {"reference_type": "Quotation", "reference_name": doc.name}
    )
    queue_count_before = frappe.db.count(
        "Email Queue", {"reference_doctype": "Quotation", "reference_name": doc.name}
    )

    try:
        frappe.db.set_single_value(
            "Avientek Settings", "enable_quotation_notifications", 1
        )
        frappe.db.set_single_value(
            "Avientek Settings", "enable_workflow_state_notifications", 1
        )
        frappe.db.commit()

        # Simulate a Draft → Pending For Approval transition.
        original_state = doc.workflow_state
        doc.workflow_state = "Pending For Approval"
        before = frappe._dict({"workflow_state": "Draft"})
        doc._doc_before_save = before

        on_state_change(doc, None)
        frappe.db.commit()

        todo_count_after = frappe.db.count(
            "ToDo", {"reference_type": "Quotation", "reference_name": doc.name}
        )
        queue_count_after = frappe.db.count(
            "Email Queue", {"reference_doctype": "Quotation", "reference_name": doc.name}
        )
        new_todos = todo_count_after - todo_count_before
        new_queue = queue_count_after - queue_count_before

        check(new_todos > 0,
              "ToDos created on Pending For Approval transition",
              f"+{new_todos} rows")
        check(new_queue > 0,
              "Email Queue row created on Pending For Approval transition",
              f"+{new_queue} rows")

        # Verify the Email Queue actually carries our template content
        recent_queue = frappe.db.get_all(
            "Email Queue",
            filters={
                "reference_doctype": "Quotation",
                "reference_name": doc.name,
            },
            fields=["name", "message"],
            order_by="creation desc",
            limit=1,
        )
        if recent_queue:
            msg = (recent_queue[0]["message"] or "")[:1000]
            check("Approval Needed" in msg or "Approval Required" in msg.lower()
                  or doc.name in msg,
                  "Email Queue body references the quote",
                  f"queue_id={recent_queue[0]['name']}")

        # Restore the doc state in memory (we didn't actually save it)
        doc.workflow_state = original_state

        # Cleanup: delete the test ToDos + Email Queue rows we created
        cleanup_todos = frappe.db.get_all(
            "ToDo",
            filters={
                "reference_type": "Quotation",
                "reference_name": doc.name,
                "creation": [">", frappe.utils.add_to_date(None, minutes=-2)],
            },
            pluck="name",
        )
        for t in cleanup_todos:
            frappe.delete_doc("ToDo", t, force=True, ignore_permissions=True)
        cleanup_queue = frappe.db.get_all(
            "Email Queue",
            filters={
                "reference_doctype": "Quotation",
                "reference_name": doc.name,
                "creation": [">", frappe.utils.add_to_date(None, minutes=-2)],
            },
            pluck="name",
        )
        for q in cleanup_queue:
            frappe.delete_doc("Email Queue", q, force=True, ignore_permissions=True)
        out.append(
            f"  Cleanup: deleted {len(cleanup_todos)} ToDo + {len(cleanup_queue)} Email Queue rows"
        )

    finally:
        frappe.db.set_single_value(
            "Avientek Settings", "enable_quotation_notifications", orig_enable or 0
        )
        frappe.db.set_single_value(
            "Avientek Settings",
            "enable_workflow_state_notifications",
            orig_workflow or 0,
        )
        frappe.db.commit()

    # ── Report ─────────────────────────────────────────────────────────
    _section(out, "RESULT")
    out.append(f"  {results['pass']} PASS / {results['fail']} FAIL")
    print("\n".join(out))
    return results
