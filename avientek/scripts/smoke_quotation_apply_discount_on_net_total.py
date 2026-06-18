"""Smoke for the 2026-06-18 apply_discount_on=Net Total fix on
Quotation `recalc_doc_totals` pipeline.

Bug reproduced on QN-KSA-26-00169 (local + prod):
  - Quote with item_amount_sum=99,687.60, discount=1,000, KSA VAT 15%,
    apply_discount_on="Net Total"
  - SAVED: net_total=99,687.60 (= total, no discount applied) and
    grand_total=113,640.74 (discount applied at end → Grand Total
    semantics, NOT Net Total)
  - User-visible: 150 SAR overcharge per quote on this scenario.

Fix at events/quotation.py recalc_doc_totals:
  - net_total now reflects the post-discount sum when apply_on=Net Total
  - per-row tax base subtracts the item's share of discount in Net Total
    mode, so tax is computed on the smaller base

This smoke covers 5 scenarios:

  A. apply_on=Net Total + discount + flat tax  →  CORRECT math
  B. apply_on=Grand Total + discount + flat tax →  legacy behavior preserved
  C. No discount + flat tax  →  identical regardless of apply_on
  D. apply_on=Net Total + discount + per-item mixed tax (18% + 28%)
       →  discount distributed pro-rata, per-item rates honored
  E. Regression guard: signature of recalc_doc_totals unchanged

Usage:
    bench --site avientekv21.local execute \
        avientek.scripts.smoke_quotation_apply_discount_on_net_total.run
"""

from types import SimpleNamespace

from avientek.events.quotation import recalc_doc_totals


def _fail(msg):
    print(f"  ✗ FAIL: {msg}")
    raise AssertionError(msg)


def _ok(msg):
    print(f"  ✓ {msg}")


def _approx(a, b, tol=0.05):
    return abs(float(a) - float(b)) <= tol


class _Item(SimpleNamespace):
    def __init__(self, **kw):
        # Required fields for recalc_doc_totals
        defaults = dict(
            qty=1, rate=0, amount=0, item_tax_rate="{}",
            shipping=0, custom_finance_value=0, custom_transport_value=0,
            reward=0, custom_incentive_value=0, custom_customs_value=0,
            custom_cogs=0, custom_selling_price=0, custom_special_price=0,
            custom_addl_discount_amount=0,
            custom_margin_value=0, custom_margin_=0,
            net_rate=0, net_amount=0,
            base_rate=0, base_amount=0,
            base_net_rate=0, base_net_amount=0,
        )
        defaults.update(kw)
        super().__init__(**defaults)

    def get(self, k, default=None):
        return getattr(self, k, default)

    def precision(self, fieldname):
        return 4

    def __contains__(self, k):
        return hasattr(self, k)


class _Tax(SimpleNamespace):
    def __init__(self, **kw):
        defaults = dict(
            charge_type="On Net Total", account_head="VAT 15% - AETL",
            rate=15, tax_amount=0, base_tax_amount=0, total=0, base_total=0,
            row_id=None,
        )
        defaults.update(kw)
        super().__init__(**defaults)


class _Doc(SimpleNamespace):
    def __init__(self, items, taxes, **kw):
        defaults = dict(
            conversion_rate=1, additional_discount_percentage=0,
            discount_amount=0, apply_discount_on="Grand Total",
            total=0, net_total=0, base_total=0, base_net_total=0,
            total_qty=0, total_taxes_and_charges=0,
            base_total_taxes_and_charges=0,
            grand_total=0, base_grand_total=0,
            rounded_total=0, base_rounded_total=0,
            custom_total_shipping_new=0, custom_total_finance_new=0,
            custom_total_transport_new=0, custom_total_reward_new=0,
            custom_total_incentive_new=0, custom_total_customs_new=0,
            custom_total_margin_new=0, custom_total_margin_percent_new=0,
            custom_total_cost_new=0, custom_total_selling_new=0,
            custom_total_buying_price=0,
            custom_quotation_brand_summary=[],
            payment_schedule=[],
        )
        defaults.update(kw)
        super().__init__(**defaults)
        self.items = items
        self.taxes = taxes

    def get(self, k, default=None):
        return getattr(self, k, default)

    def precision(self, fieldname):
        return 4


def _case_a_net_total_with_discount():
    print()
    print("=== A. apply_on=Net Total + discount + flat 15% tax ===")
    items = [_Item(qty=1, rate=99687.60, amount=99687.60, custom_selling_price=99687.60)]
    taxes = [_Tax(rate=15, charge_type="On Net Total")]
    doc = _Doc(items, taxes,
               apply_discount_on="Net Total",
               discount_amount=1000.00)
    recalc_doc_totals(doc)

    # Net Total mode: discount reduces taxable base
    if not _approx(doc.net_total, 98687.60):
        _fail(f"net_total={doc.net_total} expected 98687.60")
    if not _approx(taxes[0].tax_amount, 14803.14):
        _fail(f"tax_amount={taxes[0].tax_amount} expected 14803.14 (15% of 98687.60)")
    if not _approx(doc.grand_total, 113490.74):
        _fail(f"grand_total={doc.grand_total} expected 113490.74")
    _ok(f"net_total={doc.net_total} tax={taxes[0].tax_amount} grand={doc.grand_total}")


def _case_b_grand_total_with_discount():
    print()
    print("=== B. apply_on=Grand Total + discount + flat 15% tax (legacy preserved) ===")
    items = [_Item(qty=1, rate=99687.60, amount=99687.60, custom_selling_price=99687.60)]
    taxes = [_Tax(rate=15, charge_type="On Net Total")]
    doc = _Doc(items, taxes,
               apply_discount_on="Grand Total",
               discount_amount=1000.00)
    recalc_doc_totals(doc)

    # Grand Total mode: net_total stays full, tax on full base, discount at end
    if not _approx(doc.net_total, 99687.60):
        _fail(f"net_total={doc.net_total} expected 99687.60 (Grand Total mode)")
    if not _approx(taxes[0].tax_amount, 14953.14):
        _fail(f"tax_amount={taxes[0].tax_amount} expected 14953.14 (15% of full 99687.60)")
    if not _approx(doc.grand_total, 113640.74):
        _fail(f"grand_total={doc.grand_total} expected 113640.74 (net + tax - discount)")
    _ok(f"net_total={doc.net_total} tax={taxes[0].tax_amount} grand={doc.grand_total}")


def _case_c_no_discount():
    print()
    print("=== C. No discount → identical regardless of apply_on ===")
    for apply_on in ("Net Total", "Grand Total", ""):
        items = [_Item(qty=1, rate=99687.60, amount=99687.60, custom_selling_price=99687.60)]
        taxes = [_Tax(rate=15, charge_type="On Net Total")]
        doc = _Doc(items, taxes,
                   apply_discount_on=apply_on,
                   discount_amount=0)
        recalc_doc_totals(doc)
        if not _approx(doc.net_total, 99687.60):
            _fail(f"apply_on={apply_on!r}: net_total drift {doc.net_total}")
        if not _approx(taxes[0].tax_amount, 14953.14):
            _fail(f"apply_on={apply_on!r}: tax drift {taxes[0].tax_amount}")
        if not _approx(doc.grand_total, 114640.74):
            _fail(f"apply_on={apply_on!r}: grand drift {doc.grand_total}")
    _ok("no-discount math identical across all apply_on values")


def _case_d_per_item_mixed_rates_net_total():
    print()
    print("=== D. apply_on=Net Total + discount + per-item rates (GST 18% + 28%) ===")
    # 65" Smart Display @ GST 28%, accessory @ GST 18%
    items = [
        _Item(qty=1, rate=10000, amount=10000,
              custom_selling_price=10000,
              item_tax_rate='{"Output Tax IGST - AETPL": 28.0}'),
        _Item(qty=1, rate=5000, amount=5000,
              custom_selling_price=5000,
              item_tax_rate='{"Output Tax IGST - AETPL": 18.0}'),
    ]
    taxes = [_Tax(rate=18, charge_type="On Net Total",
                  account_head="Output Tax IGST - AETPL")]
    doc = _Doc(items, taxes,
               apply_discount_on="Net Total",
               discount_amount=300.00)
    recalc_doc_totals(doc)

    # item_amount_sum = 15000, discount 300 → discounted base = 14700
    # Pro-rata: item1 gets 200 disc (=10000-200=9800), item2 gets 100 (=5000-100=4900)
    # Tax: 9800*28% + 4900*18% = 2744.00 + 882.00 = 3626.00
    if not _approx(doc.net_total, 14700.00):
        _fail(f"net_total={doc.net_total} expected 14700.00")
    if not _approx(taxes[0].tax_amount, 3626.00):
        _fail(f"tax={taxes[0].tax_amount} expected 3626.00 (mixed 28%+18% on discounted)")
    if not _approx(doc.grand_total, 18326.00):
        _fail(f"grand={doc.grand_total} expected 18326.00 (net + mixed taxes)")
    _ok(f"per-item rates + Net Total discount: net={doc.net_total} tax={taxes[0].tax_amount} grand={doc.grand_total}")


def _case_e_signature_unchanged():
    print()
    print("=== E. recalc_doc_totals signature unchanged ===")
    import inspect
    sig = inspect.signature(recalc_doc_totals)
    params = list(sig.parameters)
    if params != ["doc"]:
        _fail(f"signature drift — expected ['doc'], got {params}")
    _ok(f"signature: recalc_doc_totals{sig}")


def _case_f_real_doc_qn_ksa_26_00169():
    print()
    print("=== F. Real local doc QN-KSA-26-00169 (the original bug repro) ===")
    import frappe
    if not frappe.db.exists("Quotation", "QN-KSA-26-00169"):
        print("  SKIP: QN-KSA-26-00169 not in local DB")
        return
    q = frappe.get_doc("Quotation", "QN-KSA-26-00169")
    recalc_doc_totals(q)
    if not _approx(q.net_total, 98687.60):
        _fail(f"net_total={q.net_total} expected 98687.60")
    if not _approx(q.total_taxes_and_charges, 14803.14):
        _fail(f"taxes={q.total_taxes_and_charges} expected 14803.14")
    if not _approx(q.grand_total, 113490.74):
        _fail(f"grand_total={q.grand_total} expected 113490.74")
    _ok(f"QN-KSA-26-00169: net={q.net_total} tax={q.total_taxes_and_charges} grand={q.grand_total}")


def run():
    print("=" * 64)
    print("Avientek smoke: Quotation apply_discount_on=Net Total fix")
    print("=" * 64)
    _case_a_net_total_with_discount()
    _case_b_grand_total_with_discount()
    _case_c_no_discount()
    _case_d_per_item_mixed_rates_net_total()
    _case_e_signature_unchanged()
    _case_f_real_doc_qn_ksa_26_00169()
    print()
    print("All smoke checks PASSED ✓")
