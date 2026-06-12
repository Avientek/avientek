"""Smoke test for the 2026-06-12 India GST autofill hook.

Covers the regression Sridhar/Jithin reported on LTD-26-27-00382:
India Sales Invoices saved without a `taxes_and_charges` template
ended up with Total GST = ₹0 because india_compliance's
ItemGSTTreatment.set_for_no_taxes() overwrote every item's
gst_treatment to "Nil-Rated" when doc.taxes was empty. The fix is
`avientek.events.utils.autofill_india_sales_taxes_template` wired on
Quotation / Sales Order / Sales Invoice before_validate.

The smoke covers 8 behavioural branches:
  1. AETPL intra-state    → picks "Output GST In-state - AETPL"
  2. AETPL inter-state    → picks "Output GST Out-state - AETPL"
  3. AETPL, place_of_supply fallback when billing GSTIN is blank
  4. Non-AETPL company    → no-op
  5. taxes_and_charges already chosen → respect, no overwrite
  6. taxes child already populated → respect, no overwrite
  7. AETPL with no GSTIN data at all → silent skip (no crash)
  8. Wrong doctype (Purchase Invoice) → no-op

Plus 3 structural checks (function present, hooks wired in order).

Usage:
    bench --site avientekv21.local execute \\
        avientek.scripts.smoke_india_gst_autofill.run
"""

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
    with open(os.path.join(_APP_ROOT, rel_path)) as f:
        return f.read()


class _FakeRow(dict):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.__dict__ = self


class _FakeDoc:
    """Mimics enough of a Frappe Document for the autofill hook.

    The hook reads via `doc.get(...)`, sets via direct attribute
    assignment, and appends to child tables via `doc.append("taxes",
    row_dict)`. No setattr metadata, no validate cascade — that's
    intentional: we exercise the SOURCE LOGIC of the hook, not
    Frappe's full validate cycle (which needs a real connected DB +
    masters that local doesn't have configured).
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self._taxes_rows = []

    def get(self, key, default=None):
        if key == "taxes":
            return self._taxes_rows
        return self.__dict__.get(key, default)

    def append(self, fieldname, row):
        if fieldname == "taxes":
            self._taxes_rows.append(_FakeRow(**row))


# ---------- structural checks ---------------------------------------


def _check_structural():
    print()
    print("=== Structural: function + hook wiring ===")

    from avientek.events import utils
    if not hasattr(utils, "autofill_india_sales_taxes_template"):
        _fail("autofill_india_sales_taxes_template missing from avientek.events.utils")
    _ok("avientek.events.utils.autofill_india_sales_taxes_template defined")

    hooks_src = _read("hooks.py")
    # Must be wired on Quotation / Sales Order / Sales Invoice
    # BEFORE the existing normalize_gst_treatment_from_template (the
    # ordering is load-bearing — normalize reads from a fresh taxes
    # table, autofill populates it first).
    #
    # Block-end finder note: doc_events doctype blocks in hooks.py are
    # indented at 4 spaces. The NEXT doctype block starts with the
    # same indent followed by `"Name": {`. Naive search for the next
    # `    "` matched the FIRST hook string inside the same block's
    # before_validate list. Use a regex anchored on the close-brace
    # pattern `\n    },\n` to find this block's real end.
    import re
    for dt in ("Sales Order", "Quotation", "Sales Invoice"):
        block_start = hooks_src.find(f'"{dt}": {{')
        if block_start < 0:
            _fail(f"hooks.py missing the {dt!r} doc_events block")
        m = re.search(r"\n    \},\n", hooks_src[block_start:])
        if not m:
            _fail(f"{dt}: could not find the close-brace of this block — hooks.py indentation drifted")
        block = hooks_src[block_start:block_start + m.end()]
        autofill_idx = block.find("autofill_india_sales_taxes_template")
        normalize_idx = block.find("normalize_gst_treatment_from_template")
        if autofill_idx < 0:
            _fail(f"{dt}: autofill_india_sales_taxes_template not wired in before_validate")
        if normalize_idx < 0:
            _fail(f"{dt}: normalize_gst_treatment_from_template wiring vanished — load-bearing dependency")
        if autofill_idx > normalize_idx:
            _fail(
                f"{dt}: autofill is wired AFTER normalize "
                f"(autofill at byte {autofill_idx}, normalize at {normalize_idx}). "
                f"Wrong order — normalize reads doc.taxes and india_compliance "
                f"runs later; autofill must populate doc.taxes FIRST."
            )
    _ok("hooks.py wires autofill BEFORE normalize on Quote / SO / SI")


# ---------- behavioural checks --------------------------------------


def _check_intra_state():
    """Case 1: company GSTIN 29 + billing GSTIN 29 → intra-state."""
    print()
    print("=== Behavioural: intra-state (29 == 29) ===")
    from avientek.events import utils
    doc = _FakeDoc(
        doctype="Sales Invoice",
        company=utils._AETPL_INDIA,
        company_gstin="29AARCA9330R1ZN",
        billing_address_gstin="29ABCDE1234F1Z5",
        place_of_supply="29-Karnataka",
        taxes_and_charges=None,
    )
    utils.autofill_india_sales_taxes_template(doc)
    if doc.taxes_and_charges != utils._AETPL_INSTATE_TEMPLATE:
        _fail(f"want {utils._AETPL_INSTATE_TEMPLATE!r}, got {doc.taxes_and_charges!r}")
    if not doc._taxes_rows:
        _fail("intra-state template was set but no taxes rows appended")
    _ok(f"intra-state → {doc.taxes_and_charges!r}, {len(doc._taxes_rows)} taxes rows appended")


def _check_inter_state():
    """Case 2: company GSTIN 29 (Karnataka) + billing GSTIN 33 (TN) → inter-state."""
    print()
    print("=== Behavioural: inter-state (29 vs 33) — the LTD-26-27-00382 case ===")
    from avientek.events import utils
    doc = _FakeDoc(
        doctype="Sales Invoice",
        company=utils._AETPL_INDIA,
        company_gstin="29AARCA9330R1ZN",  # Karnataka — Avientek's company
        billing_address_gstin="33AADFI5320G1ZV",  # Tamil Nadu — In-Sync Solutions
        place_of_supply="33-Tamil Nadu",
        taxes_and_charges=None,
    )
    utils.autofill_india_sales_taxes_template(doc)
    if doc.taxes_and_charges != utils._AETPL_OUTSTATE_TEMPLATE:
        _fail(f"want {utils._AETPL_OUTSTATE_TEMPLATE!r}, got {doc.taxes_and_charges!r}")
    if not doc._taxes_rows:
        _fail("inter-state template was set but no taxes rows appended")
    _ok(f"inter-state → {doc.taxes_and_charges!r}, {len(doc._taxes_rows)} taxes rows appended")


def _check_pos_fallback():
    """Case 3: billing GSTIN blank → fall back to place_of_supply state code."""
    print()
    print("=== Behavioural: place_of_supply fallback when billing GSTIN blank ===")
    from avientek.events import utils
    doc = _FakeDoc(
        doctype="Sales Invoice",
        company=utils._AETPL_INDIA,
        company_gstin="29AARCA9330R1ZN",
        billing_address_gstin=None,
        place_of_supply="29-Karnataka",
        taxes_and_charges=None,
    )
    utils.autofill_india_sales_taxes_template(doc)
    if doc.taxes_and_charges != utils._AETPL_INSTATE_TEMPLATE:
        _fail(f"pos fallback failed: want {utils._AETPL_INSTATE_TEMPLATE!r}, got {doc.taxes_and_charges!r}")
    _ok("pos fallback works (billing blank → state code from place_of_supply)")


def _check_non_aetpl_noop():
    """Case 4: non-AETPL company → hook is a no-op."""
    print()
    print("=== Behavioural: non-AETPL company (FZCO) → no-op ===")
    from avientek.events import utils
    doc = _FakeDoc(
        doctype="Sales Invoice",
        company="Avientek FZCO",
        company_gstin=None,
        taxes_and_charges=None,
    )
    utils.autofill_india_sales_taxes_template(doc)
    if getattr(doc, "taxes_and_charges", None) is not None:
        _fail(f"FZCO should be untouched, got taxes_and_charges={doc.taxes_and_charges!r}")
    if doc._taxes_rows:
        _fail(f"FZCO should be untouched, got {len(doc._taxes_rows)} taxes rows")
    _ok("non-AETPL company: untouched")


def _check_template_already_set():
    """Case 5: user / mapper already picked a template → preserve it."""
    print()
    print("=== Behavioural: taxes_and_charges already set → preserve ===")
    from avientek.events import utils
    doc = _FakeDoc(
        doctype="Sales Invoice",
        company=utils._AETPL_INDIA,
        company_gstin="29AARCA9330R1ZN",
        billing_address_gstin="33AADFI5320G1ZV",
        taxes_and_charges="Some Other Template",
    )
    utils.autofill_india_sales_taxes_template(doc)
    if doc.taxes_and_charges != "Some Other Template":
        _fail(f"user choice clobbered: got {doc.taxes_and_charges!r}")
    if doc._taxes_rows:
        _fail("user choice should also skip taxes-row population")
    _ok("taxes_and_charges respected — user / mapper choice preserved")


def _check_taxes_already_populated():
    """Case 6: taxes child already has rows → don't disturb."""
    print()
    print("=== Behavioural: taxes table already populated → preserve ===")
    from avientek.events import utils
    doc = _FakeDoc(
        doctype="Sales Invoice",
        company=utils._AETPL_INDIA,
        company_gstin="29AARCA9330R1ZN",
        billing_address_gstin="33AADFI5320G1ZV",
        taxes_and_charges=None,
    )
    # Pre-populate via the same .append() path the hook uses
    doc.append("taxes", {"account_head": "Manually Added - X", "rate": 18.0})
    utils.autofill_india_sales_taxes_template(doc)
    if getattr(doc, "taxes_and_charges", None) is not None:
        _fail(f"taxes already present — should skip but set "
              f"taxes_and_charges={doc.taxes_and_charges!r}")
    if len(doc._taxes_rows) != 1:
        _fail(f"taxes child polluted: had 1 manual row, now has {len(doc._taxes_rows)}")
    _ok("manually populated taxes preserved — no overwrite")


def _check_missing_gstin_skip():
    """Case 7: no GSTIN data at all → silent skip, no crash."""
    print()
    print("=== Behavioural: missing GSTIN data → silent skip ===")
    from avientek.events import utils
    doc = _FakeDoc(
        doctype="Sales Invoice",
        company=utils._AETPL_INDIA,
        company_gstin=None,
        billing_address_gstin=None,
        place_of_supply=None,
        taxes_and_charges=None,
    )
    try:
        utils.autofill_india_sales_taxes_template(doc)
    except Exception as e:
        _fail(f"hook crashed on missing GSTIN: {type(e).__name__}: {e}")
    if getattr(doc, "taxes_and_charges", None) is not None:
        _fail(f"should skip when GSTIN missing, got taxes_and_charges={doc.taxes_and_charges!r}")
    _ok("missing GSTIN: silent skip (no crash) — downstream validation will flag")


def _check_wrong_doctype():
    """Case 8: Purchase Invoice → not in scope, no-op."""
    print()
    print("=== Behavioural: Purchase Invoice → no-op (not in _INDIA_GST_DOCTYPES) ===")
    from avientek.events import utils
    doc = _FakeDoc(
        doctype="Purchase Invoice",
        company=utils._AETPL_INDIA,
        company_gstin="29AARCA9330R1ZN",
        billing_address_gstin="33AADFI5320G1ZV",
        taxes_and_charges=None,
    )
    utils.autofill_india_sales_taxes_template(doc)
    if getattr(doc, "taxes_and_charges", None) is not None:
        _fail(f"PI should be out of scope, got taxes_and_charges={doc.taxes_and_charges!r}")
    _ok("Purchase Invoice: out of scope, no-op")


# ---------- runner --------------------------------------------------


def run():
    print("=" * 64)
    print("Avientek smoke: 2026-06-12 India GST autofill hook")
    print("=" * 64)
    _check_structural()
    _check_intra_state()
    _check_inter_state()
    _check_pos_fallback()
    _check_non_aetpl_noop()
    _check_template_already_set()
    _check_taxes_already_populated()
    _check_missing_gstin_skip()
    _check_wrong_doctype()
    print()
    print("All smoke checks PASSED ✓")
