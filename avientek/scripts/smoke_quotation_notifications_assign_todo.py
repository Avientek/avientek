"""Smoke for the 2026-06-17 _assign_todo ignore_permissions=True fix.

Production audit on 2026-06-17 found 73 PermissionError entries from
quotation_notifications._assign_todo in 7 days. Root cause:
`add_assign({...})` defaults to `ignore_permissions=False`, which runs
`check_permission` on the target Quotation as the calling user. Under
PRF role-based perms (shipped 2026-06-13, commit 7a4ba0f), sales users
often lack read access to Quotes routed to other teams — the
permission check fails and spams Error Log on every workflow save.

Fix: pass `ignore_permissions=True` to add_assign. Quotation
notifications are system-driven (workflow routing), not user-driven.

Smoke verifies:

  A. The signature `add_assign(args, ignore_permissions=True)` is
     present at the call site in events/quotation_notifications.py
  B. The keyword `ignore_permissions=True` is NOT inside the args
     dict (would silently no-op — Frappe ignores unknown args keys)
  C. The fallback try/except still wraps the call (other failures
     like JSON serialize errors still go to Error Log, not propagate)
  D. add_assign itself accepts ignore_permissions as a kwarg (guards
     against Frappe renaming/removing it on a future upgrade)

Usage:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_quotation_notifications_assign_todo.run
"""

import ast
import inspect

import frappe

from avientek.events import quotation_notifications


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


def _check_call_passes_ignore_permissions_as_kwarg():
    print()
    print("=== A. add_assign call passes ignore_permissions=True ===")
    src = inspect.getsource(quotation_notifications._assign_todo)
    tree = ast.parse(src)

    found_call = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # match either add_assign(...) or frappe.desk.form.assign_to.add(...)
            if (isinstance(func, ast.Name) and func.id == "add_assign") or (
                isinstance(func, ast.Attribute) and func.attr in ("add_assign", "add")
            ):
                found_call = node
                break
    if not found_call:
        _fail("could not find add_assign() call in _assign_todo source")

    kwarg_names = {kw.arg for kw in found_call.keywords}
    if "ignore_permissions" not in kwarg_names:
        _fail("add_assign() call does NOT pass ignore_permissions kwarg")
    # Get the literal value of ignore_permissions
    for kw in found_call.keywords:
        if kw.arg == "ignore_permissions":
            val = ast.literal_eval(kw.value)
            if val is not True:
                _fail(f"ignore_permissions passed but value is {val!r} (expected True)")
            break
    _ok("call passes ignore_permissions=True as a kwarg")


def _check_no_silent_dict_key_typo():
    print()
    print("=== B. ignore_permissions is NOT inside the dict (silent no-op trap) ===")
    src = inspect.getsource(quotation_notifications._assign_todo)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                # keys can be Constant("ignore_permissions") or Str
                v = None
                if isinstance(k, ast.Constant):
                    v = k.value
                if v == "ignore_permissions":
                    _fail(
                        "ignore_permissions appears INSIDE the args dict — "
                        "Frappe will silently ignore it. Must be a kwarg "
                        "on the add_assign call instead."
                    )
    _ok("ignore_permissions only appears as a kwarg, never as a dict key")


def _check_try_except_intact():
    print()
    print("=== C. try/except around add_assign still in place ===")
    src = inspect.getsource(quotation_notifications._assign_todo)
    tree = ast.parse(src)
    has_try = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            # check the handler logs to frappe.log_error
            for h in node.handlers:
                handler_src = ast.unparse(h)
                if "frappe.log_error" in handler_src:
                    has_try = True
                    break
            if has_try:
                break
    if not has_try:
        _fail("try/except wrapper around add_assign is missing — failures would propagate")
    _ok("try/except + frappe.log_error fallback still wraps the call")


def _check_frappe_add_assign_accepts_kwarg():
    print()
    print("=== D. Frappe add_assign signature accepts ignore_permissions ===")
    from frappe.desk.form.assign_to import add as add_assign
    sig = inspect.signature(add_assign)
    if "ignore_permissions" not in sig.parameters:
        _fail(
            f"Frappe's add_assign signature changed — params: "
            f"{list(sig.parameters)}. Update the fix to match."
        )
    _ok(f"add_assign signature: {sig}")


def run():
    print("=" * 64)
    print("Avientek smoke: quotation_notifications._assign_todo ignore_permissions")
    print("=" * 64)
    _check_call_passes_ignore_permissions_as_kwarg()
    _check_no_silent_dict_key_typo()
    _check_try_except_intact()
    _check_frappe_add_assign_accepts_kwarg()
    print()
    print("All smoke checks PASSED ✓")
