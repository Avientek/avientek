"""Smoke for the 2026-06-15 PRF enhancement §3 — Post-Approval Field
Editing + Release freeze + audit trail.

Sridhar 2026-06-15 (PRF Enhancement doc): once a PRF reaches Approved
Level 2, the Finance Controller must be able to update non-financial
metadata (Issued Bank, Payment Mode, Cheque Date, Party Bank Account,
Party Address) WITHOUT a Cancel + Amend cycle — but every amount
field stays frozen, and once Released NOTHING is editable (except
System Manager break-glass). Every accepted change is captured in
Frappe's built-in Version doctype (track_changes=1 on PRF, verified).

The smoke covers:

  Structural (4):
    A. EDITABLE list in apply_fc_field_unlock JS contains all 5 fields
    B. apply_released_lock TO_LOCK contains the same 5 + the legacy 3
    C. _PRF_LOCKED_FIELDS_AFTER_SUBMIT includes the address + bank fields
    D. _PRF_TERMINAL_FROZEN_STATES is set up (Released / Processed / etc)
    E. supplier_address.allow_on_submit == 1 (post-patch)
    F. Doctype track_changes == 1 (audit trail)

  Behavioural (server-side _guard_bank_edits_after_submit, 5):
    1. FC editing issued_bank on Approved Level 2 → ALLOWED
    2. Non-FC (e.g. Sales User) editing issued_bank on Approved L2 → BLOCKED
    3. FC editing issued_bank on Released → BLOCKED (terminal freeze)
    4. System Manager editing issued_bank on Released → ALLOWED (break-glass)
    5. FC editing a field NOT in the locked list (e.g. remarks) → ALLOWED

Usage:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_prf_post_l2_fc_edit.run
"""

import frappe


# Re-import the module-level constants so the smoke fails fast if the
# names drift in payment_request_form.py.
from avientek.avientek.doctype.payment_request_form.payment_request_form import (
    _PRF_LOCKED_FIELDS_AFTER_SUBMIT,
    _PRF_BANK_EDIT_ROLES,
    _PRF_TERMINAL_FROZEN_STATES,
)


_EXPECTED_EDITABLE = (
    "issued_bank", "payment_mode", "cheque_date",
    "supplier_bank_account", "supplier_address",
)
_EXPECTED_TERMINAL = (
    "Released", "Processed", "Partially Processed",
    "Cancelled", "Cancelled (Rejected)", "Rejected",
)


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


# ----------------------------------------------------------------------
# Structural checks
# ----------------------------------------------------------------------


def _check_js_editable_list():
    print()
    print("=== Structural: JS apply_fc_field_unlock EDITABLE list ===")
    import re
    path = frappe.get_app_path("avientek", "avientek", "doctype",
                                "payment_request_form", "payment_request_form.js")
    with open(path) as f:
        src = f.read()
    m = re.search(
        r"apply_fc_field_unlock:.*?const\s+EDITABLE\s*=\s*\[(.*?)\];",
        src, re.S,
    )
    if not m:
        _fail("Could not find EDITABLE = [...] block inside apply_fc_field_unlock")
    block = m.group(1)
    for fn in _EXPECTED_EDITABLE:
        if f'"{fn}"' not in block:
            _fail(f"EDITABLE missing field {fn!r} in block: {block.strip()[:200]}")
    _ok(f"EDITABLE contains all 5 expected fields ({', '.join(_EXPECTED_EDITABLE)})")


def _check_js_released_lock():
    print()
    print("=== Structural: JS apply_released_lock TO_LOCK list ===")
    import re
    path = frappe.get_app_path("avientek", "avientek", "doctype",
                                "payment_request_form", "payment_request_form.js")
    with open(path) as f:
        src = f.read()
    m = re.search(
        r"apply_released_lock:.*?const\s+TO_LOCK\s*=\s*\[(.*?)\];",
        src, re.S,
    )
    if not m:
        _fail("Could not find TO_LOCK = [...] block inside apply_released_lock")
    block = m.group(1)
    must_include = list(_EXPECTED_EDITABLE) + [
        "additional_documents", "supplier_balance",
    ]
    for fn in must_include:
        if f'"{fn}"' not in block:
            _fail(f"TO_LOCK missing {fn!r} — terminal-state freeze would leak this field")
    _ok(f"TO_LOCK covers all {len(must_include)} fields (Release truly freezes)")


def _check_locked_fields_constant():
    print()
    print("=== Structural: _PRF_LOCKED_FIELDS_AFTER_SUBMIT covers FC-editable set ===")
    must_include = ("issued_bank", "supplier_address", "supplier_bank_account")
    missing = [fn for fn in must_include if fn not in _PRF_LOCKED_FIELDS_AFTER_SUBMIT]
    if missing:
        _fail(
            f"_PRF_LOCKED_FIELDS_AFTER_SUBMIT missing {missing!r} — "
            "server-side guard wouldn't catch changes to these fields"
        )
    _ok("_PRF_LOCKED_FIELDS_AFTER_SUBMIT covers all the address + bank fields")


def _check_terminal_frozen_states():
    print()
    print("=== Structural: _PRF_TERMINAL_FROZEN_STATES matches workflow ===")
    missing = [s for s in _EXPECTED_TERMINAL if s not in _PRF_TERMINAL_FROZEN_STATES]
    if missing:
        _fail(
            f"_PRF_TERMINAL_FROZEN_STATES missing {missing!r} — "
            "Release-freeze branch wouldn't fire for these states"
        )
    _ok(f"_PRF_TERMINAL_FROZEN_STATES = {sorted(_PRF_TERMINAL_FROZEN_STATES)}")


def _check_supplier_address_allow_on_submit():
    print()
    print("=== Property Setter: supplier_address.allow_on_submit == 1 ===")
    val = frappe.db.get_value(
        "Property Setter",
        {"doc_type": "Payment Request Form",
         "field_name": "supplier_address",
         "property": "allow_on_submit"},
        "value",
    )
    if val is None:
        # Fall back to the raw schema (in case the patch ran before
        # the Property Setter was needed for some reason).
        val = frappe.db.get_value(
            "DocField",
            {"parent": "Payment Request Form", "fieldname": "supplier_address"},
            "allow_on_submit",
        )
    if str(val) != "1":
        _fail(
            f"supplier_address.allow_on_submit = {val!r}, expected '1'. "
            "Run: bench --site <site> migrate (the patch flips it)."
        )
    _ok("supplier_address is allow_on_submit=1 — FC can save address changes post-submit")


def _check_track_changes_on():
    print()
    print("=== Audit: Payment Request Form.track_changes == 1 ===")
    track = frappe.db.get_value("DocType", "Payment Request Form", "track_changes")
    if str(track) != "1":
        _fail(
            f"track_changes = {track!r} — Frappe's Version doctype "
            "isn't capturing the audit trail. Enable in Customize Form."
        )
    _ok("track_changes ON — Frappe Version doctype captures (user, ts, old→new) per field")


# ----------------------------------------------------------------------
# Behavioural checks of _guard_bank_edits_after_submit
# ----------------------------------------------------------------------


class _StubDoc:
    """Just enough of a Document for _guard_bank_edits_after_submit.

    The guard reads: self.is_new(), self.docstatus, self.workflow_state,
    self.name, self.get_doc_before_save(), and self.get(fieldname).
    Setting `_before` on the stub provides the "previous DB row" the
    guard compares against.
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def is_new(self):
        return False

    def get_doc_before_save(self):
        return getattr(self, "_before", None)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


def _run_guard_as(roles, doc_state, before, after, name="AVFZC-99999"):
    """Run _guard_bank_edits_after_submit as a user with the given roles.
    Returns (True, None) if no exception; (False, msg) if frappe.throw.

    Monkey-patches frappe.get_roles (process-local) so we don't need a
    real user-switch via frappe.set_user — that path touches Redis
    permissions cache + email queue and we don't want the smoke to
    require Redis Queue running on local. Restores frappe.get_roles
    in finally.
    """
    from avientek.avientek.doctype.payment_request_form.payment_request_form import (
        PaymentRequestForm,
    )

    before_stub = _StubDoc(docstatus=1, **before)
    doc = _StubDoc(
        docstatus=1,
        name=name,
        workflow_state=doc_state,
        _before=before_stub,
        **after,
    )

    _original_get_roles = frappe.get_roles
    frappe.get_roles = lambda *a, **kw: list(roles)
    try:
        try:
            PaymentRequestForm._guard_bank_edits_after_submit(doc)
        except frappe.ValidationError as e:
            return False, str(e)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        return True, None
    finally:
        frappe.get_roles = _original_get_roles


def _check_behavioural():
    print()
    print("=== Behavioural: _guard_bank_edits_after_submit role × state matrix ===")
    print("    (frappe.get_roles is monkey-patched per-case so the smoke")
    print("     doesn't need Redis Queue / a real user switch)")

    # Case 1: FC editing issued_bank on Approved Level 2 → ALLOWED
    ok, err = _run_guard_as(
        ["Finance Controller"], "Approved Level 2",
        before={"issued_bank": "Bank A - FZCO"},
        after={"issued_bank": "Bank B - FZCO"},
    )
    if not ok:
        _fail(f"FC on Approved L2 should be allowed; blocked with: {err}")
    _ok("Case 1 — FC editing issued_bank on Approved Level 2: ALLOWED")

    # Case 2: Non-FC editing issued_bank on Approved L2 → BLOCKED
    ok, err = _run_guard_as(
        ["Sales User"], "Approved Level 2",
        before={"issued_bank": "Bank A - FZCO"},
        after={"issued_bank": "Bank B - FZCO"},
    )
    if ok:
        _fail("Sales User on Approved L2 should be blocked but was allowed")
    if "Finance Manager or Finance Controller" not in (err or ""):
        _fail(f"Sales User blocked but error message off: {err!r}")
    _ok("Case 2 — Sales User editing issued_bank on Approved L2: BLOCKED (correct message)")

    # Case 3: FC editing issued_bank on Released → BLOCKED (terminal freeze)
    ok, err = _run_guard_as(
        ["Finance Controller"], "Released",
        before={"issued_bank": "Bank A - FZCO"},
        after={"issued_bank": "Bank B - FZCO"},
    )
    if ok:
        _fail("FC on Released should be FROZEN but was allowed — Release freeze missing")
    if "Released" not in (err or "") and "terminal" not in (err or "").lower():
        _fail(f"FC blocked on Released but error didn't mention the state: {err!r}")
    _ok("Case 3 — FC editing issued_bank on Released: BLOCKED (terminal-state freeze)")

    # Case 4: System Manager editing issued_bank on Released → ALLOWED (break-glass)
    ok, err = _run_guard_as(
        ["System Manager"], "Released",
        before={"issued_bank": "Bank A - FZCO"},
        after={"issued_bank": "Bank B - FZCO"},
    )
    if not ok:
        _fail(f"System Manager break-glass should be allowed on Released; blocked: {err}")
    _ok("Case 4 — System Manager on Released: ALLOWED (break-glass)")

    # Case 5: FC editing a NON-locked field on Released → ALLOWED
    # (the guard only fires on changes to fields in
    # _PRF_LOCKED_FIELDS_AFTER_SUBMIT — remarks/notes aren't in there).
    ok, err = _run_guard_as(
        ["Finance Controller"], "Released",
        before={"issued_bank": "Bank A - FZCO", "remarks": "old note"},
        after={"issued_bank": "Bank A - FZCO", "remarks": "new note"},
    )
    if not ok:
        _fail(
            f"FC editing a non-locked field should be allowed; "
            f"blocked with: {err}. Guard is over-restricting."
        )
    _ok("Case 5 — FC editing non-locked field on Released: ALLOWED "
        "(guard only touches the locked set)")

    # Case 6: FC editing supplier_address (new EDITABLE field) on Approved L2 → ALLOWED
    ok, err = _run_guard_as(
        ["Finance Controller"], "Approved Level 2",
        before={"supplier_address": "Acme - Mumbai HQ"},
        after={"supplier_address": "Acme - Pune Branch"},
    )
    if not ok:
        _fail(f"FC editing supplier_address on Approved L2 should be allowed; blocked: {err}")
    _ok("Case 6 — FC editing supplier_address on Approved L2: ALLOWED")

    # Case 7: FC editing supplier_bank_account (new EDITABLE field) on Released → BLOCKED
    ok, err = _run_guard_as(
        ["Finance Controller"], "Released",
        before={"supplier_bank_account": "Acme HSBC INR"},
        after={"supplier_bank_account": "Acme ICICI INR"},
    )
    if ok:
        _fail("FC editing supplier_bank_account on Released should be FROZEN but was allowed")
    _ok("Case 7 — FC editing supplier_bank_account on Released: BLOCKED (terminal freeze)")


# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------


def run():
    print("=" * 64)
    print("Avientek smoke: PRF Enhancement §3 — Post-L2 FC edit + Release freeze")
    print("=" * 64)
    _check_js_editable_list()
    _check_js_released_lock()
    _check_locked_fields_constant()
    _check_terminal_frozen_states()
    _check_supplier_address_allow_on_submit()
    _check_track_changes_on()
    _check_behavioural()
    print()
    print("All smoke checks PASSED ✓")
