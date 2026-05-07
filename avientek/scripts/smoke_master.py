"""Master smoke — runs every recent regression check end-to-end.

Run:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_master.run

Aggregates results from:
  1. Phase A   (Sridhar 2026-05-05 #4/#11/#12)
  2. UPM removal (commit 2a2b49a — DocTypes / tables / column gone)
  3. DocPerm fix (commit 7fd0ad9 — Sales Invoice- Custom / Sales User /
                   CSM survive migrate via customize-form perms)
  4. Global UP filter (commit 1575bdf — every query report respects UP)
  5. Sridhar followups 2026-05-07 (#1/#2/#3/#5/#7/#8 — TR docs by
                   tr_type, Supplier PI input, Open PO endpoint, PV
                   Supplier Invoice No column, dynamic ref-type code,
                   per-company naming series)

Single PASS/FAIL verdict at the end. Designed to be run after every
deploy to local to catch regressions before they reach production.
"""
from __future__ import annotations

import frappe
import io
import contextlib


def _capture(fn, *args, **kwargs):
    """Capture stdout from a sub-smoke so master output stays tidy."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            ret = fn(*args, **kwargs)
            err = None
        except Exception as exc:
            ret = None
            err = repr(exc)
    return ret, buf.getvalue(), err


def run():
    print("╔" + "═" * 68 + "╗")
    print(f"║ AVIENTEK MASTER SMOKE — site: {frappe.local.site:<35s}    ║")
    print("╚" + "═" * 68 + "╝")

    summary = []

    # ── 1. Phase A — Sridhar 2026-05-05 #4 / #11 / #12 ──
    from avientek.scripts.smoke_prf_phase_a import run as phase_a_run
    ret, out, err = _capture(phase_a_run)
    if err:
        summary.append(("Phase A (#4/#11/#12)", "ERROR", err))
    else:
        ok = (ret or {}).get("fail", 1) == 0
        summary.append((
            f"Phase A (#4/#11/#12) — {ret.get('pass', 0)} pass / "
            f"{ret.get('fail', 0)} fail",
            "PASS" if ok else "FAIL",
            out,
        ))

    # ── 2. UPM removal ──
    from avientek.scripts.diag_upm_removal import run as upm_run
    ret, out, err = _capture(upm_run)
    if err:
        summary.append(("UPM removal", "ERROR", err))
    else:
        # Re-parse out for "STILL EXISTS" / "still here" markers.
        bad = ("STILL EXISTS" in out) or ("still here" in out)
        summary.append((
            "UPM/UPD doctypes + table + column removed",
            "FAIL" if bad else "PASS",
            out,
        ))

    # ── 3. DocPerm vanishing fix ──
    cdp = frappe.db.sql(
        """SELECT role, permlevel, `read`, `write`, `create`, submit, export
           FROM `tabCustom DocPerm`
           WHERE parent = 'Sales Invoice'
             AND role IN ('Sales Invoice- Custom', 'Sales User', 'CSM')
           ORDER BY role""", as_dict=True,
    )
    expected_roles = {"Sales Invoice- Custom", "Sales User", "CSM"}
    present_roles = {r["role"] for r in cdp}
    missing = expected_roles - present_roles
    perm_lines = [f"  {r['role']:25s} pl={r['permlevel']} "
                   f"r={r['read']} w={r['write']} c={r['create']} "
                   f"s={r['submit']} ex={r['export']}" for r in cdp]
    summary.append((
        "DocPerm vanishing fix (Sales Invoice / 3 roles)",
        "FAIL" if missing else "PASS",
        ("\n".join(perm_lines) +
          (f"\n  MISSING: {missing}" if missing else "")),
    ))

    # ── 4. Global User-Permission filter ──
    from avientek.scripts.smoke_global_up_filter import run as gup_run
    ret, out, err = _capture(gup_run)
    if err:
        summary.append(("Global UP filter", "ERROR", err))
    else:
        ok = bool(ret and ret.get("override_ok") and ret.get("report_builder_pass")
                   and ret.get("query_report_pass"))
        summary.append((
            "Global UP filter — Report Builder + Script Report",
            "PASS" if ok else "FAIL",
            f"override={ret.get('override_ok')} "
            f"rb={ret.get('report_builder_pass')} "
            f"qr={ret.get('query_report_pass')} "
            f"so_admin={ret.get('admin_so_count')} "
            f"so_user={ret.get('user_so_count')}",
        ))

    # ── 5. Sridhar followups 2026-05-07 ──
    from avientek.scripts.smoke_sridhar_followups import run as srid_run
    ret, out, err = _capture(srid_run)
    if err:
        summary.append(("Sridhar followups 2026-05-07", "ERROR", err))
    else:
        ok = (ret or {}).get("fail", 1) == 0
        summary.append((
            f"Sridhar followups 2026-05-07 — {ret.get('pass', 0)} pass / "
            f"{ret.get('fail', 0)} fail",
            "PASS" if ok else "FAIL",
            out,
        ))

    # ── Verdict ──
    print()
    print("─" * 70)
    print("RESULTS")
    print("─" * 70)
    pass_n = sum(1 for _, s, _ in summary if s == "PASS")
    fail_n = sum(1 for _, s, _ in summary if s != "PASS")
    for title, status, detail in summary:
        flag = "✓" if status == "PASS" else "✗"
        print(f"  {flag}  {status:5s}  {title}")
        # Print interesting detail snippets — keep terse
        if status != "PASS" and detail:
            head = detail[:600].replace("\n", "\n         ")
            print(f"         {head}")

    print()
    print("─" * 70)
    if fail_n == 0:
        print(f"  ✅  ALL {pass_n} SUITES PASSED")
    else:
        print(f"  ❌  {fail_n} SUITE(S) FAILED ({pass_n} passed)")
    print("─" * 70)

    return {"pass": pass_n, "fail": fail_n,
            "results": [{"title": t, "status": s} for t, s, _ in summary]}
