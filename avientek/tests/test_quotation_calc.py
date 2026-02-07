"""
Tests for Quotation calculation pipeline.
Verifies calc_item_totals against the corrected formula where:
  - Incentive is calculated on sp * qty
  - Customs is calculated on COGS (before markup)
  - Selling = COGS + customs + markup
"""
import unittest
from unittest.mock import MagicMock
from frappe.utils import flt, cint

# Import the functions under test
from avientek.events.quotation import (
    _to_flt,
    calc_item_totals,
    rebuild_brand_summary,
    recalc_doc_totals,
    distribute_incentive_server,
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


class TestCalcItemTotals(unittest.TestCase):
    """Verify per-item calculation with corrected formula."""

    def test_simple_all_10pct(self):
        """Verify against the user's Excel example:
        Std=100, Spl=100, all charges at 10%, qty=1
        Expected: COGS=150, customs=15, markup=15, selling=180"""
        it = make_item(
            qty=1,
            custom_standard_price_=100,
            custom_special_price=100,
            shipping_per=10,
            custom_finance_=10,
            custom_transport_=10,
            reward_per=10,
            custom_incentive_=10,
            custom_markup_=10,
            custom_customs_=10,
        )

        calc_item_totals(it)

        # shipping = 10% of std(100) = 10
        self.assertAlmostEqual(it.shipping, 10.0, places=2)
        # finance = 10% of sp(100) = 10
        self.assertAlmostEqual(it.custom_finance_value, 10.0, places=2)
        # transport = 10% of std(100) = 10
        self.assertAlmostEqual(it.custom_transport_value, 10.0, places=2)
        # reward = 10% of sp(100) = 10
        self.assertAlmostEqual(it.reward, 10.0, places=2)

        # incentive = 10% of sp*qty = 10% of 100 = 10
        self.assertAlmostEqual(it.custom_incentive_value, 10.0, places=2)

        # base = 100 + 10 + 10 + 10 + 10 = 140
        # cogs_before_customs = 140 + 10 = 150
        # markup = 10% of 150 = 15
        self.assertAlmostEqual(it.custom_markup_value, 15.0, places=2)

        # customs = 10% of 150 = 15
        self.assertAlmostEqual(it.custom_customs_value, 15.0, places=2)

        # cogs = 150 + 15 = 165
        self.assertAlmostEqual(it.custom_cogs, 165.0, places=2)

        # selling = 165 + 15 = 180
        self.assertAlmostEqual(it.custom_selling_price, 180.0, places=2)

        # margin = 15 / 180 * 100 = 8.33%
        self.assertAlmostEqual(it.custom_margin_, 8.33, places=1)

    def test_example1_qty2_no_customs(self):
        """Std=587.6, Spl=500, Ship=10%, Fin=1.5%, Trans=2%, Rew=1.5%,
        Inc=5%, Markup=100%, Customs=0%, Qty=2"""
        it = make_item(
            qty=2,
            custom_standard_price_=587.6,
            custom_special_price=500,
            shipping_per=10,
            custom_finance_=1.5,
            custom_transport_=2,
            reward_per=1.5,
            custom_incentive_=5,
            custom_markup_=100,
            custom_customs_=0,
        )

        calc_item_totals(it)

        self.assertAlmostEqual(it.shipping, 117.52, places=2)
        self.assertAlmostEqual(it.custom_finance_value, 15.0, places=2)
        self.assertAlmostEqual(it.custom_transport_value, 23.504, places=2)
        self.assertAlmostEqual(it.reward, 15.0, places=2)

        # incentive = 5% * 500 * 2 = 50.0
        self.assertAlmostEqual(it.custom_incentive_value, 50.0, places=2)

        # base = 1000 + 117.52 + 15 + 23.504 + 15 = 1171.024
        # cogs_pre = 1171.024 + 50 = 1221.024
        # markup = 100% * 1221.024 = 1221.024
        self.assertAlmostEqual(it.custom_markup_value, 1221.024, places=1)

        # customs = 0
        self.assertAlmostEqual(it.custom_customs_value, 0, places=2)

        # cogs = 1221.024
        self.assertAlmostEqual(it.custom_cogs, 1221.024, places=1)

        # selling = 1221.024 + 1221.024 = 2442.048
        self.assertAlmostEqual(it.custom_selling_price, 2442.05, places=0)

        # margin = 50%
        self.assertAlmostEqual(it.custom_margin_, 50.0, places=0)

    def test_example2_qty1_customs1(self):
        """Std=271.73, Spl=250, Ship=20%, Fin=2%, Trans=1.5%,
        Rew=1.5%, Inc=5%, Markup=21%, Customs=1%, Qty=1"""
        it = make_item(
            qty=1,
            custom_standard_price_=271.73,
            custom_special_price=250,
            shipping_per=20,
            custom_finance_=2,
            custom_transport_=1.5,
            reward_per=1.5,
            custom_incentive_=5,
            custom_markup_=21,
            custom_customs_=1,
        )

        calc_item_totals(it)

        self.assertAlmostEqual(it.shipping, 54.35, places=1)
        self.assertAlmostEqual(it.custom_finance_value, 5.00, places=2)
        self.assertAlmostEqual(it.custom_transport_value, 4.08, places=1)
        self.assertAlmostEqual(it.reward, 3.75, places=2)

        # incentive = 5% * 250 = 12.5
        self.assertAlmostEqual(it.custom_incentive_value, 12.5, places=2)

        # base = 250 + 54.346 + 5 + 4.076 + 3.75 = 317.172
        # cogs_pre = 317.172 + 12.5 = 329.672
        # markup = 21% * 329.672 = 69.2311
        self.assertAlmostEqual(it.custom_markup_value, 69.23, places=1)

        # customs = 1% * 329.672 = 3.2967
        self.assertAlmostEqual(it.custom_customs_value, 3.30, places=1)

        # cogs = 329.672 + 3.2967 = 332.969
        self.assertAlmostEqual(it.custom_cogs, 332.97, places=1)

        # selling = 332.969 + 69.231 = 402.20
        self.assertAlmostEqual(it.custom_selling_price, 402.20, places=0)

        # margin% = 69.23 / 402.20 * 100 = 17.22%
        self.assertAlmostEqual(it.custom_margin_, 17.2, places=0)

    def test_example3_qty1_customs1_lower_markup(self):
        """Std=160, Spl=140, Ship=20%, Fin=2%, Trans=1.5%,
        Rew=1.5%, Inc=3%, Markup=15%, Customs=1%, Qty=1"""
        it = make_item(
            qty=1,
            custom_standard_price_=160,
            custom_special_price=140,
            shipping_per=20,
            custom_finance_=2,
            custom_transport_=1.5,
            reward_per=1.5,
            custom_incentive_=3,
            custom_markup_=15,
            custom_customs_=1,
        )

        calc_item_totals(it)

        self.assertAlmostEqual(it.shipping, 32.0, places=2)
        self.assertAlmostEqual(it.custom_finance_value, 2.80, places=2)
        self.assertAlmostEqual(it.custom_transport_value, 2.40, places=2)
        self.assertAlmostEqual(it.reward, 2.10, places=2)

        # incentive = 3% * 140 = 4.2
        self.assertAlmostEqual(it.custom_incentive_value, 4.2, places=2)

        # base = 140 + 32 + 2.8 + 2.4 + 2.1 = 179.3
        # cogs_pre = 179.3 + 4.2 = 183.5
        # markup = 15% * 183.5 = 27.525
        self.assertAlmostEqual(it.custom_markup_value, 27.525, places=1)

        # customs = 1% * 183.5 = 1.835
        self.assertAlmostEqual(it.custom_customs_value, 1.835, places=2)

        # cogs = 183.5 + 1.835 = 185.335
        self.assertAlmostEqual(it.custom_cogs, 185.335, places=1)

        # selling = 185.335 + 27.525 = 212.86
        self.assertAlmostEqual(it.custom_selling_price, 212.86, places=0)

        # margin% = 27.525 / 212.86 * 100 = 12.93%
        self.assertAlmostEqual(it.custom_margin_, 12.93, places=0)


class TestRecalcDocTotals(unittest.TestCase):
    """Verify parent-level totals are summed correctly from items."""

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

        self.assertAlmostEqual(
            doc.custom_total_selling_new,
            it1.custom_selling_price + it2.custom_selling_price,
            places=2,
        )
        self.assertAlmostEqual(
            doc.custom_total_cost_new,
            it1.custom_cogs + it2.custom_cogs,
            places=2,
        )
        expected_margin = (
            doc.custom_total_selling_new - doc.custom_total_cost_new
        )
        self.assertAlmostEqual(doc.custom_total_margin_new, expected_margin, places=2)

        if doc.custom_total_selling_new:
            expected_pct = expected_margin / doc.custom_total_selling_new * 100
            self.assertAlmostEqual(doc.custom_total_margin_percent_new, expected_pct, places=1)


class TestDistributeIncentive(unittest.TestCase):
    """Verify incentive distribution logic (proportional to sp*qty)."""

    def test_proportional_distribution(self):
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

        # Incentive should be distributed proportional to sp*qty
        # it1 sp*qty = 250, it2 sp*qty = 140, total = 390
        # it1 share = 250/390 * 50 = 32.05, it2 share = 140/390 * 50 = 17.95
        total_distributed = it1.custom_incentive_value + it2.custom_incentive_value
        self.assertAlmostEqual(total_distributed, total_incentive, places=2)

        self.assertAlmostEqual(it1.custom_incentive_value, 250.0 / 390.0 * 50, places=1)
        self.assertAlmostEqual(it2.custom_incentive_value, 140.0 / 390.0 * 50, places=1)


class TestFullPipeline(unittest.TestCase):
    """Verify run_calculation_pipeline end-to-end."""

    def test_pipeline_runs_without_error(self):
        it1 = make_item(
            qty=2, custom_standard_price_=587.6, custom_special_price=500,
            shipping_per=10, custom_finance_=1.5, custom_transport_=2,
            reward_per=1.5, custom_incentive_=5, custom_markup_=100, custom_customs_=0,
        )

        doc = make_doc([it1])
        run_calculation_pipeline(doc)

        # selling = 2442.05 (with corrected incentive on sp*qty)
        self.assertAlmostEqual(it1.custom_selling_price, 2442.05, places=0)
        self.assertAlmostEqual(doc.custom_total_selling_new, 2442.05, places=0)
        self.assertAlmostEqual(doc.custom_total_margin_percent_new, 50.0, places=0)


if __name__ == "__main__":
    unittest.main()
