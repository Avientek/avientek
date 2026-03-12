"""
Tests for Quotation calculation pipeline.
Covers:
  - Per-item calculation (calc_item_totals) with various charge combos
  - Multi-item parent totals (recalc_doc_totals)
  - Item-level net_rate / net_amount syncing with additional discount
  - Incentive distribution (proportional, equal, manual)
  - Discount distribution (single item, multi-item)
  - Full pipeline end-to-end (add items, change values, remove items)
  - Edge cases (zero qty, zero price, all-zero charges, negative guard)
"""
import unittest
from unittest.mock import MagicMock
import frappe
from frappe.utils import flt, cint

# Ensure frappe.get_system_settings works outside a site context so that
# flt(value, precision) can call rounded() without raising.
_real_get_system_settings = getattr(frappe, "get_system_settings", None)


def _mock_get_system_settings(key=None):
    settings = {"rounding_method": "Banker's Rounding (legacy)"}
    if key:
        return settings.get(key)
    return settings


frappe.get_system_settings = _mock_get_system_settings

# Import the functions under test
from avientek.events.quotation import (
    _to_flt,
    calc_item_totals,
    rebuild_brand_summary,
    recalc_doc_totals,
    distribute_incentive_server,
    distribute_discount_server,
    run_calculation_pipeline,
)


def make_item(**kwargs):
    """Create a mock Quotation Item child row."""
    defaults = {
        "qty": 1,
        "custom_standard_price_": 0,
        "custom_special_price": 0,
        "shipping_per": 0,
        "custom_finance_": 0,
        "custom_transport_": 0,
        "reward_per": 0,
        "custom_incentive_": 0,
        "custom_markup_": 0,
        "custom_customs_": 0,
        "brand": "TestBrand",
        # output fields (will be set by calc)
        "shipping": 0,
        "custom_finance_value": 0,
        "custom_transport_value": 0,
        "reward": 0,
        "custom_incentive_value": 0,
        "custom_markup_value": 0,
        "custom_cogs": 0,
        "custom_total_": 0,
        "custom_customs_value": 0,
        "custom_selling_price": 0,
        "custom_margin_": 0,
        "custom_margin_value": 0,
        "custom_special_rate": 0,
        "rate": 0,
        "amount": 0,
        "custom_discount_amount_value": 0,
        "custom_discount_amount_qty": 0,
        # ERPNext standard fields synced by recalc_doc_totals
        "net_rate": 0,
        "net_amount": 0,
        "base_rate": 0,
        "base_amount": 0,
        "base_net_rate": 0,
        "base_net_amount": 0,
    }
    defaults.update(kwargs)

    item = MagicMock()
    for k, v in defaults.items():
        setattr(item, k, v)

    # Make .update() work like a real frappe doc
    def update_fn(d):
        for k, v in d.items():
            setattr(item, k, v)
    item.update = update_fn

    # Make .get() work
    item.get = lambda k, default=None: getattr(item, k, default)

    return item


def make_doc(items, **parent_kwargs):
    """Create a mock Quotation parent doc."""
    doc = MagicMock()
    doc.items = items

    defaults = {
        "custom_incentive_": 0,
        "custom_incentive_amount": 0,
        "custom_distribute_incentive_based_on": "Amount",
        "custom_discount_amount_value": 0,
        "custom_quotation_brand_summary": [],
        "custom_total_shipping_new": 0,
        "custom_total_finance_new": 0,
        "custom_total_transport_new": 0,
        "custom_total_reward_new": 0,
        "custom_total_incentive_new": 0,
        "custom_total_customs_new": 0,
        "custom_total_margin_new": 0,
        "custom_total_margin_percent_new": 0,
        "custom_total_cost_new": 0,
        "custom_total_selling_new": 0,
        "custom_total_buying_price": 0,
        "additional_discount_percentage": 0,
        "discount_amount": 0,
        "conversion_rate": 1,
        "total_qty": 0,
        "total": 0,
        "net_total": 0,
        "base_total": 0,
        "base_net_total": 0,
        "grand_total": 0,
        "base_grand_total": 0,
        "rounded_total": 0,
        "base_rounded_total": 0,
    }
    defaults.update(parent_kwargs)
    for k, v in defaults.items():
        setattr(doc, k, v)

    doc.get = lambda k, default=None: getattr(doc, k, default)

    # For rebuild_brand_summary
    summary_rows = []
    def set_fn(fieldname, val):
        if fieldname == "custom_quotation_brand_summary":
            summary_rows.clear()
    def append_fn(fieldname, row):
        if fieldname == "custom_quotation_brand_summary":
            summary_rows.append(row)
    doc.set = set_fn
    doc.append = append_fn
    doc._summary_rows = summary_rows

    return doc


# ──────────────────────────────────────────────────────────────
# 1) PER-ITEM CALCULATIONS
# ──────────────────────────────────────────────────────────────
class TestCalcItemTotals(unittest.TestCase):
    """Verify per-item calculation with corrected formula."""

    def test_simple_all_10pct(self):
        """All charges at 10%, Std=Spl=100, qty=1."""
        it = make_item(
            qty=1,
            custom_standard_price_=100,
            custom_special_price=100,
            shipping_per=10, custom_finance_=10, custom_transport_=10,
            reward_per=10, custom_incentive_=10, custom_markup_=10,
            custom_customs_=10,
        )
        calc_item_totals(it)

        self.assertAlmostEqual(it.shipping, 10.0, places=2)
        self.assertAlmostEqual(it.custom_finance_value, 10.0, places=2)
        self.assertAlmostEqual(it.custom_transport_value, 10.0, places=2)
        self.assertAlmostEqual(it.reward, 10.0, places=2)
        self.assertAlmostEqual(it.custom_incentive_value, 10.0, places=2)
        # base=140, cogs_pre=150, customs=15, cogs=165, markup=16.5
        self.assertAlmostEqual(it.custom_customs_value, 15.0, places=2)
        self.assertAlmostEqual(it.custom_cogs, 165.0, places=2)
        self.assertAlmostEqual(it.custom_markup_value, 16.5, places=2)
        self.assertAlmostEqual(it.custom_selling_price, 181.5, places=2)
        self.assertAlmostEqual(it.custom_margin_, 9.09, places=1)
        # ERPNext sync fields
        self.assertAlmostEqual(it.rate, 181.5, places=2)
        self.assertAlmostEqual(it.amount, 181.5, places=2)
        self.assertAlmostEqual(it.custom_special_rate, 181.5, places=2)

    def test_qty2_no_customs(self):
        """Std=587.6, Spl=500, qty=2, customs=0%."""
        it = make_item(
            qty=2,
            custom_standard_price_=587.6, custom_special_price=500,
            shipping_per=10, custom_finance_=1.5, custom_transport_=2,
            reward_per=1.5, custom_incentive_=5, custom_markup_=100,
            custom_customs_=0,
        )
        calc_item_totals(it)

        self.assertAlmostEqual(it.shipping, 117.52, places=2)
        self.assertAlmostEqual(it.custom_finance_value, 15.0, places=2)
        self.assertAlmostEqual(it.custom_transport_value, 23.504, places=2)
        self.assertAlmostEqual(it.reward, 15.0, places=2)
        self.assertAlmostEqual(it.custom_incentive_value, 50.0, places=2)
        self.assertAlmostEqual(it.custom_customs_value, 0, places=2)
        self.assertAlmostEqual(it.custom_cogs, 1221.024, places=1)
        self.assertAlmostEqual(it.custom_markup_value, 1221.024, places=1)
        self.assertAlmostEqual(it.custom_selling_price, 2442.05, places=0)
        self.assertAlmostEqual(it.custom_margin_, 50.0, places=0)
        # Per-unit selling = 2442.048 / 2
        self.assertAlmostEqual(it.custom_special_rate, 1221.024, places=1)

    def test_qty1_with_customs(self):
        """Std=271.73, Spl=250, customs=1%, markup=21%."""
        it = make_item(
            qty=1,
            custom_standard_price_=271.73, custom_special_price=250,
            shipping_per=20, custom_finance_=2, custom_transport_=1.5,
            reward_per=1.5, custom_incentive_=5, custom_markup_=21,
            custom_customs_=1,
        )
        calc_item_totals(it)

        self.assertAlmostEqual(it.shipping, 54.35, places=1)
        self.assertAlmostEqual(it.custom_finance_value, 5.00, places=2)
        self.assertAlmostEqual(it.custom_transport_value, 4.08, places=1)
        self.assertAlmostEqual(it.reward, 3.75, places=2)
        self.assertAlmostEqual(it.custom_incentive_value, 12.5, places=2)
        self.assertAlmostEqual(it.custom_customs_value, 3.30, places=1)
        self.assertAlmostEqual(it.custom_cogs, 332.97, places=1)
        self.assertAlmostEqual(it.custom_markup_value, 69.92, places=1)
        self.assertAlmostEqual(it.custom_selling_price, 402.89, places=0)
        self.assertAlmostEqual(it.custom_margin_, 17.4, places=0)

    def test_lower_markup_with_customs(self):
        """Std=160, Spl=140, customs=1%, markup=15%."""
        it = make_item(
            qty=1,
            custom_standard_price_=160, custom_special_price=140,
            shipping_per=20, custom_finance_=2, custom_transport_=1.5,
            reward_per=1.5, custom_incentive_=3, custom_markup_=15,
            custom_customs_=1,
        )
        calc_item_totals(it)

        self.assertAlmostEqual(it.shipping, 32.0, places=2)
        self.assertAlmostEqual(it.custom_finance_value, 2.80, places=2)
        self.assertAlmostEqual(it.custom_transport_value, 2.40, places=2)
        self.assertAlmostEqual(it.reward, 2.10, places=2)
        self.assertAlmostEqual(it.custom_incentive_value, 4.2, places=2)
        self.assertAlmostEqual(it.custom_customs_value, 1.835, places=2)
        self.assertAlmostEqual(it.custom_cogs, 185.335, places=1)
        self.assertAlmostEqual(it.custom_markup_value, 27.80, places=1)
        self.assertAlmostEqual(it.custom_selling_price, 213.14, places=0)
        self.assertAlmostEqual(it.custom_margin_, 13.04, places=0)

    def test_zero_charges(self):
        """Only standard/special price set, all charges zero."""
        it = make_item(
            qty=3, custom_standard_price_=500, custom_special_price=400,
        )
        calc_item_totals(it)

        # selling = sp * qty = 1200 (no charges, no markup)
        self.assertAlmostEqual(it.shipping, 0, places=2)
        self.assertAlmostEqual(it.custom_incentive_value, 0, places=2)
        self.assertAlmostEqual(it.custom_cogs, 1200, places=2)
        self.assertAlmostEqual(it.custom_selling_price, 1200, places=2)
        self.assertAlmostEqual(it.custom_margin_, 0, places=2)
        self.assertAlmostEqual(it.rate, 400, places=2)

    def test_discount_fields_reset(self):
        """calc_item_totals resets discount fields to 0."""
        it = make_item(
            qty=1, custom_standard_price_=100, custom_special_price=100,
            custom_discount_amount_value=50, custom_discount_amount_qty=50,
        )
        calc_item_totals(it)

        self.assertEqual(it.custom_discount_amount_value, 0)
        self.assertEqual(it.custom_discount_amount_qty, 0)

    def test_high_qty_scaling(self):
        """Verify charges scale linearly with qty."""
        it1 = make_item(
            qty=1, custom_standard_price_=100, custom_special_price=100,
            shipping_per=10, custom_incentive_=5, custom_markup_=20,
        )
        it10 = make_item(
            qty=10, custom_standard_price_=100, custom_special_price=100,
            shipping_per=10, custom_incentive_=5, custom_markup_=20,
        )
        calc_item_totals(it1)
        calc_item_totals(it10)

        # Shipping should be 10x, selling price should be 10x
        self.assertAlmostEqual(it10.shipping, it1.shipping * 10, places=2)
        self.assertAlmostEqual(it10.custom_selling_price, it1.custom_selling_price * 10, places=1)
        # Per-unit rate should be the same
        self.assertAlmostEqual(it10.rate, it1.rate, places=2)

    def test_real_quotation_qn_fzco_26_00579(self):
        """Reproduce the actual quotation QN-FZCO-26-00579 item values."""
        it = make_item(
            qty=1,
            custom_standard_price_=2250,
            custom_special_price=2250,
            shipping_per=0, custom_finance_=0, custom_transport_=0,
            reward_per=0, custom_incentive_=10, custom_markup_=10,
            custom_customs_=0,
        )
        calc_item_totals(it)

        # base = 2250, incentive = 225, cogs = 2475, markup = 247.5
        self.assertAlmostEqual(it.custom_incentive_value, 225, places=2)
        self.assertAlmostEqual(it.custom_cogs, 2475, places=2)
        self.assertAlmostEqual(it.custom_markup_value, 247.5, places=2)
        self.assertAlmostEqual(it.custom_selling_price, 2722.5, places=2)
        self.assertAlmostEqual(it.rate, 2722.5, places=2)


# ──────────────────────────────────────────────────────────────
# 2) PARENT TOTALS & ITEM-LEVEL NET FIELD SYNC
# ──────────────────────────────────────────────────────────────
class TestRecalcDocTotals(unittest.TestCase):
    """Verify parent-level totals and item-level ERPNext field sync."""

    def test_totals_from_two_items(self):
        it1 = make_item(
            qty=1, custom_standard_price_=271.73, custom_special_price=250,
            shipping_per=20, custom_finance_=2, custom_transport_=1.5,
            reward_per=1.5, custom_incentive_=5, custom_markup_=21, custom_customs_=1,
        )
        it2 = make_item(
            qty=1, custom_standard_price_=160, custom_special_price=140,
            shipping_per=20, custom_finance_=2, custom_transport_=1.5,
            reward_per=1.5, custom_incentive_=3, custom_markup_=15, custom_customs_=1,
        )
        calc_item_totals(it1)
        calc_item_totals(it2)

        doc = make_doc([it1, it2])
        recalc_doc_totals(doc)

        total_selling = it1.custom_selling_price + it2.custom_selling_price
        total_cost = it1.custom_cogs + it2.custom_cogs
        self.assertAlmostEqual(doc.custom_total_selling_new, total_selling, places=2)
        self.assertAlmostEqual(doc.custom_total_cost_new, total_cost, places=2)
        self.assertAlmostEqual(doc.total, total_selling, places=2)
        self.assertAlmostEqual(doc.grand_total, total_selling, places=2)

    def test_item_net_fields_no_additional_discount(self):
        """Without additional discount, net_rate == rate, net_amount == amount."""
        it = make_item(
            qty=2, custom_standard_price_=100, custom_special_price=100,
            custom_markup_=20,
        )
        calc_item_totals(it)

        doc = make_doc([it])
        recalc_doc_totals(doc)

        self.assertAlmostEqual(it.net_rate, it.rate, places=4)
        self.assertAlmostEqual(it.net_amount, it.amount, places=4)

    def test_item_net_fields_with_additional_discount_percentage(self):
        """With 12% additional discount, net fields must reflect the discount."""
        it = make_item(
            qty=1, custom_standard_price_=2250, custom_special_price=2250,
            custom_incentive_=10, custom_markup_=10,
        )
        calc_item_totals(it)
        # selling = 2722.50

        doc = make_doc([it], additional_discount_percentage=12)
        recalc_doc_totals(doc)

        # addl_discount = 12% of 2722.50 = 326.70
        expected_addl = flt(2722.5 * 12 / 100, 4)
        expected_net_amount = flt(2722.5 - expected_addl, 4)

        self.assertAlmostEqual(it.net_amount, expected_net_amount, places=2)
        self.assertAlmostEqual(it.net_rate, expected_net_amount, places=2)  # qty=1
        self.assertAlmostEqual(doc.grand_total, expected_net_amount, places=2)

    def test_item_net_fields_multi_item_proportional_discount(self):
        """Additional discount distributed proportionally across 2 items."""
        it1 = make_item(
            qty=1, custom_standard_price_=200, custom_special_price=200,
            custom_markup_=25,
        )
        it2 = make_item(
            qty=2, custom_standard_price_=100, custom_special_price=100,
            custom_markup_=50,
        )
        calc_item_totals(it1)
        calc_item_totals(it2)
        # it1 selling = 250, it2 selling = 300, total = 550

        doc = make_doc([it1, it2], additional_discount_percentage=10)
        recalc_doc_totals(doc)

        total_selling = it1.amount + it2.amount  # before recalc changed them
        addl_disc = flt(total_selling * 10 / 100, 4)

        # Check proportional distribution
        it1_disc = flt(addl_disc * 250 / 550, 4)
        it2_disc = flt(addl_disc * 300 / 550, 4)

        self.assertAlmostEqual(it1.net_amount, flt(250 - it1_disc, 4), places=2)
        self.assertAlmostEqual(it2.net_amount, flt(300 - it2_disc, 4), places=2)
        # net_rate = net_amount / qty
        self.assertAlmostEqual(it2.net_rate, flt(it2.net_amount / 2, 4), places=2)

    def test_base_currency_conversion(self):
        """Base fields use conversion_rate."""
        it = make_item(
            qty=1, custom_standard_price_=100, custom_special_price=100,
            custom_markup_=10,
        )
        calc_item_totals(it)
        # selling = 110

        doc = make_doc([it], conversion_rate=3.6725)
        recalc_doc_totals(doc)

        self.assertAlmostEqual(it.base_rate, flt(110 * 3.6725, 4), places=2)
        self.assertAlmostEqual(it.base_amount, flt(110 * 3.6725, 4), places=2)
        self.assertAlmostEqual(it.base_net_rate, flt(110 * 3.6725, 4), places=2)
        self.assertAlmostEqual(doc.base_total, flt(110 * 3.6725, 4), places=2)
        self.assertAlmostEqual(doc.base_grand_total, flt(110 * 3.6725, 4), places=2)

    def test_base_currency_with_additional_discount(self):
        """Base fields correctly reflect additional discount with conversion."""
        it = make_item(
            qty=1, custom_standard_price_=1000, custom_special_price=1000,
            custom_markup_=20,
        )
        calc_item_totals(it)
        # selling = 1200

        doc = make_doc([it], conversion_rate=3.6725, additional_discount_percentage=10)
        recalc_doc_totals(doc)

        addl = flt(1200 * 10 / 100, 4)  # 120
        net_amt = flt(1200 - addl, 4)    # 1080
        self.assertAlmostEqual(it.net_amount, net_amt, places=2)
        self.assertAlmostEqual(it.base_net_amount, flt(net_amt * 3.6725, 4), places=2)
        self.assertAlmostEqual(doc.grand_total, net_amt, places=2)
        self.assertAlmostEqual(doc.base_grand_total, flt(net_amt * 3.6725, 4), places=2)

    def test_discount_amount_synced_from_percentage(self):
        """When additional_discount_percentage is set, discount_amount is synced."""
        it = make_item(
            qty=1, custom_standard_price_=1000, custom_special_price=1000,
            custom_markup_=0,
        )
        calc_item_totals(it)

        doc = make_doc([it], additional_discount_percentage=15)
        recalc_doc_totals(doc)

        self.assertAlmostEqual(doc.discount_amount, flt(1000 * 15 / 100, 4), places=2)


# ──────────────────────────────────────────────────────────────
# 3) INCENTIVE DISTRIBUTION
# ──────────────────────────────────────────────────────────────
class TestDistributeIncentive(unittest.TestCase):
    """Verify incentive distribution across items."""

    def test_proportional_two_items(self):
        it1 = make_item(
            qty=1, custom_standard_price_=271.73, custom_special_price=250,
            shipping_per=20, custom_finance_=2, custom_transport_=1.5,
            reward_per=1.5, custom_incentive_=0, custom_markup_=21, custom_customs_=1,
        )
        it2 = make_item(
            qty=1, custom_standard_price_=160, custom_special_price=140,
            shipping_per=20, custom_finance_=2, custom_transport_=1.5,
            reward_per=1.5, custom_incentive_=0, custom_markup_=15, custom_customs_=1,
        )
        calc_item_totals(it1)
        calc_item_totals(it2)

        total_incentive = 50.0
        doc = make_doc(
            [it1, it2],
            custom_incentive_amount=total_incentive,
            custom_distribute_incentive_based_on="Amount",
        )
        distribute_incentive_server(doc)

        # sp*qty: it1=250, it2=140, total=390
        total_distributed = it1.custom_incentive_value + it2.custom_incentive_value
        self.assertAlmostEqual(total_distributed, total_incentive, places=2)
        self.assertAlmostEqual(it1.custom_incentive_value, 250.0 / 390.0 * 50, places=1)
        self.assertAlmostEqual(it2.custom_incentive_value, 140.0 / 390.0 * 50, places=1)

    def test_equal_distribution(self):
        """Distributed Equally: each item gets equal share."""
        it1 = make_item(
            qty=1, custom_standard_price_=500, custom_special_price=400,
            custom_incentive_=0, custom_markup_=10,
        )
        it2 = make_item(
            qty=1, custom_standard_price_=100, custom_special_price=80,
            custom_incentive_=0, custom_markup_=10,
        )
        calc_item_totals(it1)
        calc_item_totals(it2)

        doc = make_doc(
            [it1, it2],
            custom_incentive_amount=60,
            custom_distribute_incentive_based_on="Distributed Equally",
        )
        distribute_incentive_server(doc)

        self.assertAlmostEqual(it1.custom_incentive_value, 30, places=2)
        self.assertAlmostEqual(it2.custom_incentive_value, 30, places=2)

    def test_manual_distribution_skipped(self):
        """Distributed Manually: distribute_incentive_server does nothing."""
        it = make_item(
            qty=1, custom_standard_price_=100, custom_special_price=100,
            custom_incentive_=5, custom_markup_=10,
        )
        calc_item_totals(it)
        original_incentive = it.custom_incentive_value

        doc = make_doc(
            [it],
            custom_incentive_amount=999,
            custom_distribute_incentive_based_on="Distributed Manually",
        )
        distribute_incentive_server(doc)

        # Should not change
        self.assertAlmostEqual(it.custom_incentive_value, original_incentive, places=2)

    def test_incentive_overrides_item_level(self):
        """Parent incentive overrides item-level incentive percentage."""
        it = make_item(
            qty=1, custom_standard_price_=1000, custom_special_price=1000,
            custom_incentive_=10, custom_markup_=20,
        )
        calc_item_totals(it)
        # item-level incentive = 10% of 1000 = 100

        doc = make_doc([it], custom_incentive_amount=200)
        distribute_incentive_server(doc)

        # Parent incentive 200 overrides item 100
        self.assertAlmostEqual(it.custom_incentive_value, 200, places=2)
        # COGS = (1000 - 100 + 200) = 1200 (removed old 100, added new 200)
        # Wait, cogs from calc_item_totals = 1000 + 100 = 1100, markup = 220
        # distribute: cogs_without_incentive = 1100 - 100 = 1000
        # adjusted_cost = 1000 + 200 = 1200
        # selling = 1200 + 220 = 1420
        self.assertAlmostEqual(it.custom_cogs, 1200, places=2)
        self.assertAlmostEqual(it.custom_selling_price, 1420, places=2)

    def test_incentive_updates_margin(self):
        """After incentive distribution, margin is recalculated."""
        it = make_item(
            qty=1, custom_standard_price_=500, custom_special_price=500,
            custom_incentive_=0, custom_markup_=10,
        )
        calc_item_totals(it)
        # cogs=500, markup=50, selling=550, margin=50/550=9.09%

        doc = make_doc([it], custom_incentive_amount=100)
        distribute_incentive_server(doc)

        # new cogs = 500+100=600, markup stays 50, selling = 650
        # margin = 50/650 = 7.69%
        self.assertAlmostEqual(it.custom_cogs, 600, places=2)
        self.assertAlmostEqual(it.custom_selling_price, 650, places=2)
        self.assertAlmostEqual(it.custom_margin_value, 50, places=2)
        self.assertAlmostEqual(it.custom_margin_, flt(50 / 650 * 100, 4), places=1)

    def test_negative_incentive_rejected(self):
        """Negative incentive amount should be rejected."""
        it = make_item(
            qty=1, custom_standard_price_=100, custom_special_price=100,
            custom_markup_=10,
        )
        calc_item_totals(it)
        original_selling = it.custom_selling_price

        doc = make_doc([it], custom_incentive_amount=-50)
        distribute_incentive_server(doc)

        # Should not change
        self.assertAlmostEqual(it.custom_selling_price, original_selling, places=2)


# ──────────────────────────────────────────────────────────────
# 4) DISCOUNT DISTRIBUTION
# ──────────────────────────────────────────────────────────────
class TestDistributeDiscount(unittest.TestCase):
    """Verify discount distribution across items."""

    def test_single_item_discount(self):
        """Full discount applied to single item."""
        it = make_item(
            qty=1, custom_standard_price_=2250, custom_special_price=2250,
            custom_incentive_=10, custom_markup_=10,
        )
        calc_item_totals(it)
        # selling = 2722.50, cogs = 2475

        doc = make_doc([it], custom_discount_amount_value=20)
        distribute_discount_server(doc)

        self.assertAlmostEqual(it.custom_selling_price, 2702.50, places=2)
        self.assertAlmostEqual(it.custom_discount_amount_qty, 20, places=2)
        self.assertAlmostEqual(it.custom_discount_amount_value, 20, places=2)
        self.assertAlmostEqual(it.rate, 2702.50, places=2)
        # margin = 2702.50 - 2475 = 227.50
        self.assertAlmostEqual(it.custom_margin_value, 227.50, places=2)
        self.assertAlmostEqual(
            it.custom_margin_,
            flt(227.50 / 2702.50 * 100, 4),
            places=1,
        )

    def test_multi_item_proportional_discount(self):
        """Discount distributed proportionally by selling price."""
        it1 = make_item(
            qty=1, custom_standard_price_=200, custom_special_price=200,
            custom_markup_=25,
        )
        it2 = make_item(
            qty=1, custom_standard_price_=300, custom_special_price=300,
            custom_markup_=25,
        )
        calc_item_totals(it1)
        calc_item_totals(it2)
        # it1 selling = 250, it2 selling = 375, total = 625

        doc = make_doc([it1, it2], custom_discount_amount_value=100)
        distribute_discount_server(doc)

        # it1 share = 250/625 = 0.4, disc = 40
        # it2 share = 375/625 = 0.6, disc = 60
        self.assertAlmostEqual(it1.custom_discount_amount_qty, 40, places=2)
        self.assertAlmostEqual(it2.custom_discount_amount_qty, 60, places=2)
        self.assertAlmostEqual(it1.custom_selling_price, 210, places=2)
        self.assertAlmostEqual(it2.custom_selling_price, 315, places=2)

    def test_discount_with_qty(self):
        """discount_amount_value is per-unit, discount_amount_qty is total."""
        it = make_item(
            qty=5, custom_standard_price_=100, custom_special_price=100,
            custom_markup_=20,
        )
        calc_item_totals(it)
        # selling = 600 (100*5 + 20%*500 = 600)

        doc = make_doc([it], custom_discount_amount_value=50)
        distribute_discount_server(doc)

        # total discount = 50, per unit = 50/5 = 10
        self.assertAlmostEqual(it.custom_discount_amount_qty, 50, places=2)
        self.assertAlmostEqual(it.custom_discount_amount_value, 10, places=2)
        self.assertAlmostEqual(it.custom_selling_price, 550, places=2)
        self.assertAlmostEqual(it.rate, 110, places=2)  # 550/5

    def test_negative_discount_rejected(self):
        """Negative discount should be rejected."""
        it = make_item(
            qty=1, custom_standard_price_=100, custom_special_price=100,
            custom_markup_=10,
        )
        calc_item_totals(it)
        original = it.custom_selling_price

        doc = make_doc([it], custom_discount_amount_value=-20)
        distribute_discount_server(doc)

        self.assertAlmostEqual(it.custom_selling_price, original, places=2)

    def test_discount_larger_than_selling_clamps_to_zero(self):
        """Discount larger than selling price clamps selling to 0."""
        it = make_item(
            qty=1, custom_standard_price_=100, custom_special_price=100,
        )
        calc_item_totals(it)
        # selling = 100

        doc = make_doc([it], custom_discount_amount_value=200)
        distribute_discount_server(doc)

        self.assertAlmostEqual(it.custom_selling_price, 0, places=2)


# ──────────────────────────────────────────────────────────────
# 5) FULL PIPELINE END-TO-END
# ──────────────────────────────────────────────────────────────
class TestFullPipeline(unittest.TestCase):
    """Simulate realistic user scenarios through the full pipeline."""

    def test_single_item_no_extras(self):
        """Single item, no incentive/discount at parent level."""
        it = make_item(
            qty=2, custom_standard_price_=587.6, custom_special_price=500,
            shipping_per=10, custom_finance_=1.5, custom_transport_=2,
            reward_per=1.5, custom_incentive_=5, custom_markup_=100,
        )
        doc = make_doc([it], custom_incentive_amount=50)
        run_calculation_pipeline(doc)

        self.assertAlmostEqual(it.custom_selling_price, 2442.05, places=0)
        self.assertAlmostEqual(doc.custom_total_selling_new, 2442.05, places=0)
        self.assertAlmostEqual(doc.custom_total_margin_percent_new, 50.0, places=0)

    def test_real_qn_fzco_26_00579_with_discount_and_addl_discount(self):
        """Full reproduction of QN-FZCO-26-00579 including net_rate sync."""
        it = make_item(
            qty=1,
            custom_standard_price_=2250, custom_special_price=2250,
            custom_incentive_=10, custom_markup_=10,
        )
        doc = make_doc(
            [it],
            custom_discount_amount_value=20,
            additional_discount_percentage=12,
            conversion_rate=3.6725,
        )
        run_calculation_pipeline(doc)

        # After calc_item_totals: selling = 2722.50
        # After distribute_discount: selling = 2722.50 - 20 = 2702.50
        self.assertAlmostEqual(it.custom_selling_price, 2702.50, places=2)
        self.assertAlmostEqual(it.rate, 2702.50, places=2)
        self.assertAlmostEqual(it.custom_cogs, 2475, places=2)
        self.assertAlmostEqual(it.custom_margin_value, 227.50, places=2)

        # Parent totals
        self.assertAlmostEqual(doc.total, 2702.50, places=2)
        addl = flt(2702.50 * 12 / 100, 4)
        self.assertAlmostEqual(doc.grand_total, flt(2702.50 - addl, 4), places=2)

        # Item-level net fields (THE FIX)
        expected_net = flt(2702.50 - addl, 4)
        self.assertAlmostEqual(it.net_amount, expected_net, places=2)
        self.assertAlmostEqual(it.net_rate, expected_net, places=2)
        self.assertAlmostEqual(
            it.base_net_amount, flt(expected_net * 3.6725, 4), places=2
        )
        self.assertAlmostEqual(
            it.base_rate, flt(2702.50 * 3.6725, 4), places=2
        )

    def test_multi_item_with_incentive_and_discount(self):
        """3 items, parent incentive + parent discount + additional discount."""
        it1 = make_item(
            qty=2, custom_standard_price_=500, custom_special_price=400,
            shipping_per=5, custom_finance_=2, custom_markup_=20,
        )
        it2 = make_item(
            qty=1, custom_standard_price_=1000, custom_special_price=800,
            shipping_per=10, custom_transport_=3, custom_markup_=15,
        )
        it3 = make_item(
            qty=3, custom_standard_price_=200, custom_special_price=150,
            custom_incentive_=5, custom_markup_=25,
        )
        doc = make_doc(
            [it1, it2, it3],
            custom_incentive_amount=100,
            custom_discount_amount_value=50,
            additional_discount_percentage=5,
            conversion_rate=3.6725,
        )
        run_calculation_pipeline(doc)

        # Verify no NaN or negative values
        for it in [it1, it2, it3]:
            self.assertGreaterEqual(it.custom_selling_price, 0)
            self.assertGreaterEqual(it.custom_cogs, 0)
            self.assertGreaterEqual(it.net_amount, 0)
            self.assertGreater(it.rate, 0)
            self.assertGreater(it.base_rate, 0)
            self.assertGreater(it.net_rate, 0)

        # Total selling = sum of all item amounts
        total_selling = it1.amount + it2.amount + it3.amount
        self.assertAlmostEqual(doc.total, total_selling, places=2)

        # Grand total = total - 5% additional discount
        expected_grand = flt(total_selling - total_selling * 5 / 100, 4)
        self.assertAlmostEqual(doc.grand_total, expected_grand, places=1)

        # Sum of net_amounts should equal grand_total
        sum_net = it1.net_amount + it2.net_amount + it3.net_amount
        self.assertAlmostEqual(sum_net, doc.grand_total, places=1)

    def test_add_item_then_save_again(self):
        """Simulate: save with 1 item, then add another and save again."""
        it1 = make_item(
            qty=1, custom_standard_price_=500, custom_special_price=500,
            custom_markup_=10,
        )

        # First save
        doc = make_doc([it1], custom_discount_amount_value=10)
        run_calculation_pipeline(doc)
        first_selling = it1.custom_selling_price

        # Add second item and re-save
        it2 = make_item(
            qty=2, custom_standard_price_=300, custom_special_price=300,
            custom_markup_=20,
        )
        doc.items = [it1, it2]
        run_calculation_pipeline(doc)

        # it1 selling recalculated from scratch (discount reset then reapplied)
        # Discount of 10 now split between 2 items proportionally
        total_disc = it1.custom_discount_amount_qty + it2.custom_discount_amount_qty
        self.assertAlmostEqual(total_disc, 10, places=2)
        total_selling = it1.custom_selling_price + it2.custom_selling_price
        self.assertAlmostEqual(doc.total, total_selling, places=2)

    def test_remove_all_charges(self):
        """Set all charges to 0 — selling = sp * qty."""
        it = make_item(
            qty=5, custom_standard_price_=100, custom_special_price=100,
        )
        doc = make_doc([it])
        run_calculation_pipeline(doc)

        self.assertAlmostEqual(it.custom_selling_price, 500, places=2)
        self.assertAlmostEqual(it.custom_cogs, 500, places=2)
        self.assertAlmostEqual(it.custom_margin_, 0, places=2)
        self.assertAlmostEqual(doc.total, 500, places=2)
        self.assertAlmostEqual(doc.grand_total, 500, places=2)

    def test_change_markup_resave(self):
        """Simulate user changing markup % and re-saving."""
        it = make_item(
            qty=1, custom_standard_price_=1000, custom_special_price=1000,
            custom_markup_=10,
        )
        doc = make_doc([it])
        run_calculation_pipeline(doc)
        self.assertAlmostEqual(it.custom_selling_price, 1100, places=2)

        # User changes markup to 25%
        it.custom_markup_ = 25
        run_calculation_pipeline(doc)
        self.assertAlmostEqual(it.custom_selling_price, 1250, places=2)
        self.assertAlmostEqual(it.custom_markup_value, 250, places=2)

    def test_change_qty_resave(self):
        """Simulate user changing qty and re-saving."""
        it = make_item(
            qty=1, custom_standard_price_=100, custom_special_price=100,
            shipping_per=10, custom_markup_=20,
        )
        doc = make_doc([it])
        run_calculation_pipeline(doc)
        rate_q1 = it.rate

        # Change qty to 5
        it.qty = 5
        run_calculation_pipeline(doc)

        # Per-unit rate stays the same
        self.assertAlmostEqual(it.rate, rate_q1, places=2)
        # Total amount = rate * qty
        self.assertAlmostEqual(it.amount, rate_q1 * 5, places=1)
        self.assertAlmostEqual(it.shipping, 50, places=2)  # 10% * 100 * 5

    def test_change_special_price_resave(self):
        """Simulate user changing special_price and re-saving."""
        it = make_item(
            qty=1, custom_standard_price_=500, custom_special_price=400,
            custom_incentive_=5, custom_markup_=15,
        )
        doc = make_doc([it])
        run_calculation_pipeline(doc)
        old_selling = it.custom_selling_price

        # User increases special_price
        it.custom_special_price = 450
        run_calculation_pipeline(doc)

        # Selling should increase
        self.assertGreater(it.custom_selling_price, old_selling)
        # Incentive recalculated on new sp
        self.assertAlmostEqual(it.custom_incentive_value, flt(5 * 450 / 100, 4), places=2)

    def test_zero_discount_clears_item_discounts(self):
        """When parent discount is 0, item discounts should be 0."""
        it = make_item(
            qty=1, custom_standard_price_=1000, custom_special_price=1000,
            custom_markup_=10,
            # Stale discount from previous save
            custom_discount_amount_value=50,
            custom_discount_amount_qty=50,
        )
        doc = make_doc([it], custom_discount_amount_value=0)
        run_calculation_pipeline(doc)

        # calc_item_totals resets to 0, and no discount distribution runs
        self.assertEqual(it.custom_discount_amount_value, 0)
        self.assertEqual(it.custom_discount_amount_qty, 0)
        self.assertAlmostEqual(it.custom_selling_price, 1100, places=2)

    def test_pipeline_with_three_brands(self):
        """Multiple items with different brands — brand summary built."""
        it1 = make_item(
            qty=1, custom_standard_price_=100, custom_special_price=100,
            custom_markup_=10, brand="BrandA",
        )
        it2 = make_item(
            qty=1, custom_standard_price_=200, custom_special_price=200,
            custom_markup_=20, brand="BrandB",
        )
        it3 = make_item(
            qty=1, custom_standard_price_=150, custom_special_price=150,
            custom_markup_=15, brand="BrandA",
        )
        doc = make_doc([it1, it2, it3])
        run_calculation_pipeline(doc)

        # Brand summary should have 2 entries (BrandA, BrandB)
        self.assertEqual(len(doc._summary_rows), 2)

    def test_full_pipeline_net_amount_consistency(self):
        """Sum of item net_amounts must equal doc grand_total."""
        items = []
        for i in range(5):
            it = make_item(
                qty=i + 1,
                custom_standard_price_=(i + 1) * 100,
                custom_special_price=(i + 1) * 80,
                shipping_per=5,
                custom_markup_=15 + i * 5,
                custom_incentive_=2,
                brand=f"Brand{i % 3}",
            )
            items.append(it)

        doc = make_doc(
            items,
            custom_incentive_amount=50,
            custom_discount_amount_value=30,
            additional_discount_percentage=8,
            conversion_rate=3.6725,
        )
        run_calculation_pipeline(doc)

        # Sum of net_amounts must match grand_total
        sum_net = sum(flt(it.net_amount) for it in items)
        self.assertAlmostEqual(sum_net, doc.grand_total, places=1)

        # Sum of amounts must match total
        sum_amt = sum(flt(it.amount) for it in items)
        self.assertAlmostEqual(sum_amt, doc.total, places=1)

        # Base grand total = grand_total * conversion_rate
        self.assertAlmostEqual(
            doc.base_grand_total,
            flt(doc.grand_total * 3.6725, 4),
            places=1,
        )

        # No item should have negative selling or net_amount
        for it in items:
            self.assertGreaterEqual(it.custom_selling_price, 0)
            self.assertGreaterEqual(it.net_amount, 0)
            self.assertGreater(it.base_rate, 0)


# ──────────────────────────────────────────────────────────────
# 6) EDGE CASES
# ──────────────────────────────────────────────────────────────
class TestEdgeCases(unittest.TestCase):

    def test_zero_special_price(self):
        """Zero special price should not cause division by zero."""
        it = make_item(
            qty=1, custom_standard_price_=100, custom_special_price=0,
            custom_markup_=10,
        )
        calc_item_totals(it)
        self.assertAlmostEqual(it.custom_selling_price, 0, places=2)

    def test_zero_qty_treated_as_one(self):
        """qty=0 is treated as 1 to avoid division by zero."""
        it = make_item(
            qty=0, custom_standard_price_=100, custom_special_price=100,
            custom_markup_=10,
        )
        calc_item_totals(it)
        # Should compute as qty=1
        self.assertAlmostEqual(it.custom_selling_price, 110, places=2)
        self.assertAlmostEqual(it.rate, 110, places=2)

    def test_empty_items_list(self):
        """Pipeline with no items should not error."""
        doc = make_doc([])
        run_calculation_pipeline(doc)
        self.assertAlmostEqual(doc.total, 0, places=2)
        self.assertAlmostEqual(doc.grand_total, 0, places=2)

    def test_very_large_values(self):
        """Large prices and quantities should calculate correctly."""
        it = make_item(
            qty=1000,
            custom_standard_price_=50000,
            custom_special_price=45000,
            shipping_per=5,
            custom_finance_=2,
            custom_transport_=3,
            custom_incentive_=8,
            custom_markup_=25,
            custom_customs_=5,
        )
        doc = make_doc([it], conversion_rate=3.6725)
        run_calculation_pipeline(doc)

        self.assertGreater(it.custom_selling_price, 0)
        self.assertGreater(it.custom_cogs, 0)
        self.assertGreater(doc.grand_total, 0)
        # Margin should be reasonable (markup=25% => ~20% margin)
        self.assertGreater(it.custom_margin_, 10)
        self.assertLess(it.custom_margin_, 30)

    def test_string_values_handled(self):
        """_to_flt handles string and None values gracefully."""
        self.assertAlmostEqual(_to_flt("123.45"), 123.45, places=2)
        self.assertAlmostEqual(_to_flt(""), 0, places=2)
        self.assertAlmostEqual(_to_flt(None), 0, places=2)
        self.assertAlmostEqual(_to_flt(0), 0, places=2)
        self.assertAlmostEqual(_to_flt("$1,234.56"), 1234.56, places=2)


if __name__ == "__main__":
    unittest.main()
