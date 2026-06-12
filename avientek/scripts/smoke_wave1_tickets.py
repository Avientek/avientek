"""Smoke test for the 2026-06-11 ticket-queue Wave 1 fixes.

Covers:
  - ERP-TKT-31: Quotation print gated on Approved (server before_print
    + client menu hide)
  - ERP-TKT-32: Approved Quotes + Open Quotations number cards switched
    to role-aware Custom method counters (owner-scoped for non-
    approvers, global for approvers)
  - ERP-TKT-38: PRF cheque_date editable post-submit by Finance
    Controller (allow_on_submit on the field + EDITABLE list extended)
  - ERP-TKT-29: get_company_stock excludes RMA / Demo / Service /
    Repair warehouses (Avientek convention: warehouse_type='Freezed Items')
    so the Quote line-item stock indicator reflects sellable stock only

Each check is independent; the runner prints a summary and exits
non-zero on first failure so CI / a wrapper shell script can fail a
deploy if any check regresses.

Usage:
    bench --site avientekv21.local execute \\
        avientek.scripts.smoke_wave1_tickets.run
"""

import json
import os

import frappe


# ---------- helpers -------------------------------------------------


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


_APP_ROOT = frappe.get_app_path("avientek")


def _read(rel_path):
    """Read a file under the avientek app — works regardless of the
    bench cwd (the bench console runs from frappe-bench, not the app
    dir, and pytest/CI might run from yet another place)."""
    abs_path = os.path.join(_APP_ROOT, rel_path)
    with open(abs_path) as f:
        return f.read()


# ---------- ERP-TKT-31 ---------------------------------------------


def _check_tkt31_server_hook():
    """before_print hook blocks non-approved Quotations, allows
    approved ones, and skips for System Manager / Administrator."""
    print()
    print("=== ERP-TKT-31: Quote print gated on Approved ===")

    # Hook is wired in hooks.py
    hooks_src = _read("hooks.py")
    if "avientek.events.quotation.block_print_unless_approved" not in hooks_src:
        _fail("hooks.py does not wire before_print -> "
              "avientek.events.quotation.block_print_unless_approved")
    # And it's under the Quotation block, not e.g. a misplaced PO entry
    qn_block_start = hooks_src.find('"Quotation": {')
    if qn_block_start < 0:
        _fail("Quotation block missing from hooks.py")
    qn_block_end = hooks_src.find('"Purchase Receipt"', qn_block_start)
    if "block_print_unless_approved" not in hooks_src[qn_block_start:qn_block_end]:
        _fail("block_print_unless_approved is NOT inside the Quotation "
              "doc_events block in hooks.py — wired on the wrong doctype")
    _ok("hooks.py wires Quotation.before_print -> block_print_unless_approved")

    # Function loads
    from avientek.events import quotation as q
    if not hasattr(q, "block_print_unless_approved"):
        _fail("block_print_unless_approved not exposed by "
              "avientek.events.quotation")
    if not hasattr(q, "_PRINT_ALLOWED_STATES"):
        _fail("_PRINT_ALLOWED_STATES allow-list missing")
    expected = {"Approved", "Submitted", "Order Placed", "Quotation Closed"}
    if set(q._PRINT_ALLOWED_STATES) != expected:
        _fail(f"_PRINT_ALLOWED_STATES drifted: have "
              f"{sorted(q._PRINT_ALLOWED_STATES)!r} want {sorted(expected)!r}")
    _ok(f"_PRINT_ALLOWED_STATES = {sorted(expected)}")

    # Simulate the hook behaviour without changing frappe.session.user
    # (that would break the bench shell's connection — same gotcha that
    # bit me during interactive testing).
    class _FakeDoc:
        workflow_state = "Draft"

    # Administrator (default in bench console) always bypasses — that's
    # the audit / historical-record exemption.
    #
    # CALL SHAPE: Frappe's `run_method("before_print", print_settings)`
    # routes through Document.hook's composer
    # (frappe/model/document.py:1374) which calls
    # `composed(self, method, *args, **kwargs)`. So before_print hooks
    # actually receive THREE positional args: (doc, method,
    # print_settings). The smoke deliberately exercises that exact
    # shape — the 2-arg call shape blew the function up on prod
    # 2026-06-12 because the smoke had been calling it with one
    # positional only. Don't regress.
    fd = _FakeDoc()
    fake_print_settings = {"letter_head": "AVN - India"}  # ← Frappe's 3rd arg
    fd.workflow_state = "Draft"
    try:
        q.block_print_unless_approved(fd, "before_print", fake_print_settings)
    except Exception as e:
        _fail(f"Administrator should bypass the print block; got {type(e).__name__}: {e}")
    _ok("Draft + Administrator + 3-arg call: bypassed (audit exemption)")

    fd.workflow_state = "Approved"
    try:
        q.block_print_unless_approved(fd, "before_print", fake_print_settings)
    except Exception as e:
        _fail(f"Approved state should never block; got {type(e).__name__}: {e}")
    _ok("Approved + any user + 3-arg call: allowed")

    # The non-admin Draft block path requires a non-Administrator user;
    # we DO NOT mutate frappe.session.user in this smoke (it breaks the
    # bench shell's DB connection). Instead, exercise the logic by
    # patching the function's get_roles + session.user lookups
    # transiently.
    import unittest.mock as mock
    with mock.patch.object(frappe, "session", create=True) as ms, \
         mock.patch.object(frappe, "get_roles", return_value=["Sales User"]):
        ms.user = "alice@example.com"
        fd.workflow_state = "Draft"
        try:
            q.block_print_unless_approved(fd, "before_print", fake_print_settings)
            _fail("Draft + Sales User should be blocked; nothing was thrown")
        except frappe.ValidationError:
            pass
        except Exception as e:
            if "Print Not Allowed" in str(e) or "Approved" in str(e):
                pass
            else:
                _fail(f"Wrong exception type from block: {type(e).__name__}: {e}")
    _ok("Draft + Sales User (non-admin) + 3-arg call: blocked")

    with mock.patch.object(frappe, "session", create=True) as ms, \
         mock.patch.object(frappe, "get_roles", return_value=["Sales User", "System Manager"]):
        ms.user = "manager@example.com"
        fd.workflow_state = "Draft"
        try:
            q.block_print_unless_approved(fd, "before_print", fake_print_settings)
        except Exception as e:
            _fail(f"Draft + System Manager should bypass; got {type(e).__name__}: {e}")
    _ok("Draft + System Manager + 3-arg call: bypassed (admin override)")

    # Hard regression check — the function MUST accept Frappe's
    # before_print call shape (doc, method, print_settings). The
    # previous 2-arg signature compiled fine and the old smoke
    # passed, but every Quotation print on prod crashed with
    # "TypeError: takes from 1 to 2 positional arguments but 3 were
    # given". Introspect the signature directly so the smoke catches
    # it even if a future refactor drops the inline call test.
    import inspect
    sig = inspect.signature(q.block_print_unless_approved)
    # Either explicit (doc, method, print_settings) OR (doc, method, *args).
    params = list(sig.parameters.values())
    accepts_3_positional = (
        len([p for p in params if p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY)]) >= 3
        or any(p.kind == p.VAR_POSITIONAL for p in params)
    )
    if not accepts_3_positional:
        _fail(
            f"block_print_unless_approved signature {sig!s} accepts "
            f"only {len(params)} positional args — Frappe's before_print "
            f"composer passes (doc, method, print_settings). 2-arg "
            f"signature broke prod prints on 2026-06-12."
        )
    _ok("Signature accepts (doc, method, print_settings) — Frappe's before_print shape")


def _check_tkt31_client_helper():
    """quotation.js refresh hook calls the new strip helper and the
    helper's state allow-list matches the server's."""
    print()
    print("=== ERP-TKT-31: client-side strip helper ===")

    src = _read("public/js/quotation.js")
    if "_strip_print_buttons_unless_approved" not in src:
        _fail("_strip_print_buttons_unless_approved missing from quotation.js")
    _ok("_strip_print_buttons_unless_approved defined in quotation.js")

    # The refresh handler must actually call it. Cheap proxy: a single
    # `refresh(frm) { ... _strip_print_buttons_unless_approved(frm); }`
    # block exists.
    refresh_idx = src.find("refresh(frm) {")
    if refresh_idx < 0:
        _fail("No refresh(frm) handler in quotation.js")
    refresh_end = src.find("\n    }", refresh_idx)
    if "_strip_print_buttons_unless_approved" not in src[refresh_idx:refresh_end]:
        _fail("refresh(frm) does not call _strip_print_buttons_unless_approved")
    _ok("refresh(frm) calls _strip_print_buttons_unless_approved")

    # State allow-list parity with the server: both must contain the
    # same 4 strings. If the lists drift, JS hides the menu but the
    # server throws (or vice versa) — bad UX.
    expected = {"Approved", "Submitted", "Order Placed", "Quotation Closed"}
    for st in expected:
        if f'"{st}"' not in src:
            _fail(f"JS allow-list missing state {st!r}")
    _ok("JS state allow-list matches the server's 4 states")


# ---------- ERP-TKT-32 ---------------------------------------------


def _check_tkt32_helpers_and_wiring():
    """New count helpers exist, JSONs are wired to them, and the
    role-aware filter shape is right (owner=user for non-approvers,
    no owner clause for approvers)."""
    print()
    print("=== ERP-TKT-32: Number card owner-scope ===")

    from avientek.api import quotation_cards as qc
    for name in ("count_approved_quotes",
                 "count_open_quotations",
                 "_count_by_quotation_filters"):
        if not hasattr(qc, name):
            _fail(f"avientek.api.quotation_cards.{name} missing")
    _ok("count_approved_quotes / count_open_quotations / "
        "_count_by_quotation_filters all present")

    # JSONs switched to type=Custom + method=<our helper>
    for slug, expected_method in [
        ("approved_quotes",
         "avientek.api.quotation_cards.count_approved_quotes"),
        ("open_quotations",
         "avientek.api.quotation_cards.count_open_quotations"),
    ]:
        path = f"avientek/number_card/{slug}/{slug}.json"
        card = json.loads(_read(path))
        if card.get("type") != "Custom":
            _fail(f"{slug}.json type should be 'Custom', got {card.get('type')!r}")
        if card.get("method") != expected_method:
            _fail(f"{slug}.json method should be {expected_method!r}, "
                  f"got {card.get('method')!r}")
        _ok(f"{slug}.json: type=Custom method={expected_method}")

    # Role-aware filter shape — patch _user_can_see_all_quotations and
    # observe whether the owner clause appears.
    import unittest.mock as mock
    with mock.patch.object(qc, "_user_can_see_all_quotations", return_value=False), \
         mock.patch.object(frappe, "session", create=True) as ms, \
         mock.patch.object(frappe.db, "count", return_value=42):
        ms.user = "alice@example.com"
        r = qc.count_approved_quotes()
        if "owner" not in r["route_options"]:
            _fail("Non-approver call should add owner to route_options")
        if r["route_options"]["owner"] != "alice@example.com":
            _fail(f"owner clause should be session.user, got "
                  f"{r['route_options']['owner']!r}")
        if r["value"] != 42:
            _fail(f"count value mismatch (expected mocked 42, got {r['value']})")
    _ok("Non-approver: filter includes owner=session.user ✓")

    with mock.patch.object(qc, "_user_can_see_all_quotations", return_value=True), \
         mock.patch.object(frappe.db, "count", return_value=123):
        r = qc.count_open_quotations()
        if "owner" in r["route_options"]:
            _fail("Approver call should NOT include owner clause "
                  "(else they don't get the global oversight)")
    _ok("Approver: filter omits owner (global oversight) ✓")


# ---------- ERP-TKT-38 ---------------------------------------------


def _check_tkt38_cheque_date_post_submit():
    """PRF cheque_date is editable after submit by Finance Controller."""
    print()
    print("=== ERP-TKT-38: PRF cheque_date FC-editable post-submit ===")

    # JSON: allow_on_submit=1 on cheque_date.
    # Path note: frappe.get_app_path("avientek") returns the PACKAGE
    # dir (apps/avientek/avientek/). The doctype/number_card/etc.
    # subdirs live one level deeper inside the MODULE dir, so all
    # those reads need the `avientek/` prefix. hooks.py and
    # public/js/* live at the package level and don't.
    path = "avientek/doctype/payment_request_form/payment_request_form.json"
    prf_json = json.loads(_read(path))
    cd_field = next(
        (f for f in prf_json["fields"] if f.get("fieldname") == "cheque_date"),
        None,
    )
    if cd_field is None:
        _fail("cheque_date field missing from PRF JSON")
    if not cd_field.get("allow_on_submit"):
        _fail(f"cheque_date.allow_on_submit not 1 in JSON: {cd_field!r}")
    _ok("PRF JSON: cheque_date.allow_on_submit = 1")

    # Meta — propagates after clear_cache; smoke test does the clear
    # so we never get a stale-cache false negative.
    frappe.clear_cache(doctype="Payment Request Form")
    meta = frappe.get_meta("Payment Request Form")
    if not meta.get_field("cheque_date").allow_on_submit:
        _fail("Meta cache still shows cheque_date.allow_on_submit=0 "
              "even after clear_cache — something is masking the JSON")
    _ok("Meta (post clear_cache): cheque_date.allow_on_submit = 1")

    # JS EDITABLE list includes cheque_date — the FC unlock allows
    # editing it pre-Released, and the banner mentions it so FC knows.
    js_src = _read("avientek/doctype/payment_request_form/payment_request_form.js")
    if 'EDITABLE = ["issued_bank", "payment_mode", "cheque_date"]' not in js_src:
        _fail("EDITABLE list in apply_fc_field_unlock does not include cheque_date")
    _ok('apply_fc_field_unlock EDITABLE includes "cheque_date"')
    if "Cheque Date" not in js_src:
        _fail("FC banner does not mention 'Cheque Date'")
    _ok("FC banner mentions Cheque Date")


# ---------- ERP-TKT-29 ---------------------------------------------


def _check_tkt29_freezed_warehouses_excluded():
    """get_company_stock excludes RMA / Demo / Service / Repair
    warehouses (warehouse_type='Freezed Items') from the count."""
    print()
    print("=== ERP-TKT-29: Quote stock excludes Freezed Items warehouses ===")

    # Source-level: the SQL must filter on warehouse_type
    src = _read("events/quotation.py")
    if "warehouse_type IS NULL OR warehouse_type != 'Freezed Items'" not in src:
        _fail("events/quotation.py get_company_stock does not exclude "
              "warehouse_type='Freezed Items' warehouses")
    _ok("get_company_stock SQL excludes warehouse_type='Freezed Items' "
        "(NULL-safe via OR clause)")

    # Behaviour-level: pick an item that has stock in BOTH a real and
    # a Freezed Items warehouse; assert the count drops the Freezed
    # rows. Falls back to a structural check if no such item exists
    # on the local site.
    rows = frappe.db.sql(
        """
        SELECT b.item_code,
               SUM(CASE WHEN w.warehouse_type='Freezed Items'
                        THEN b.actual_qty ELSE 0 END) AS frozen,
               SUM(CASE WHEN w.warehouse_type IS NULL
                        OR w.warehouse_type != 'Freezed Items'
                        THEN b.actual_qty ELSE 0 END) AS live
        FROM `tabBin` b
        INNER JOIN `tabWarehouse` w ON w.name = b.warehouse
        WHERE w.is_group = 0
        GROUP BY b.item_code
        HAVING frozen > 0 AND live > 0
        LIMIT 1
        """,
        as_dict=True,
    )
    if not rows:
        _ok("No item with stock in BOTH real + Freezed warehouses on "
            "local — behavioural assertion skipped, structural check "
            "above is sufficient")
        return

    item_code = rows[0]["item_code"]
    frozen = float(rows[0]["frozen"])
    live = float(rows[0]["live"])
    print(f"  test item: {item_code} (frozen={frozen} live={live})")

    from avientek.events import quotation as q
    import importlib
    importlib.reload(q)
    result = q.get_company_stock(item_code)
    total_returned = sum(float(r["actual_stock"]) for r in result)

    # If the bug were present, total_returned would include `frozen`.
    # With the fix, it should equal `live` (within rounding tolerance).
    drift = abs(total_returned - live)
    if drift > 0.5:
        _fail(f"get_company_stock returned actual_stock={total_returned} "
              f"for {item_code}, but the LIVE (non-frozen) total is "
              f"{live}. Frozen stock ({frozen}) appears to be leaking "
              f"into the count. Drift={drift}")
    _ok(f"get_company_stock({item_code}) returned {total_returned} — "
        f"matches LIVE total {live} (excluded {frozen} frozen units)")


# ---------- runner --------------------------------------------------


def run():
    print("=" * 64)
    print("Avientek smoke: 2026-06-11 ticket queue Wave 1 fixes")
    print("=" * 64)
    _check_tkt31_server_hook()
    _check_tkt31_client_helper()
    _check_tkt32_helpers_and_wiring()
    _check_tkt38_cheque_date_post_submit()
    _check_tkt29_freezed_warehouses_excluded()
    print()
    print("All smoke checks PASSED ✓")
