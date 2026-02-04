"""
Tests for Quotation calculation pipeline.
Verifies calc_item_totals against the 3 worked examples from the client's
ERP_Next.ods Quote sheet (rows 53-56, 85-88, 95-98).
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
    """Verify per-item calculation against client spreadsheet examples."""

    def test_example1_qty2_no_customs(self):
        """Row 53-56: Std=587.6, Spl=500, Ship=10%, Fin=1.5%, Trans=2%, Rew=1.5%,
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

        # Per-unit expected: shipping=58.76, finance=7.5, transport=11.752, reward=7.5
        # Total shipping = 58.76*2 = 117.52, etc.
        self.assertAlmostEqual(it.shipping, 117.52, places=2)
        self.assertAlmostEqual(it.custom_finance_value, 15.0, places=2)
        self.assertAlmostEqual(it.custom_transport_value, 23.504, places=2)
        self.assertAlmostEqual(it.reward, 15.0, places=2)

        # base = 1000 + 117.52 + 15 + 23.504 + 15 = 1171.024
        # incentive = 5% * 1171.024 = 58.5512
        self.assertAlmostEqual(it.custom_incentive_value, 58.5512, places=2)

        # cogs_pre = 1171.024 + 58.5512 = 1229.5752
        # markup = 100% * 1229.5752 = 1229.5752
        self.assertAlmostEqual(it.custom_markup_value, 1229.5752, places=1)

        # total = 1229.5752 + 1229.5752 = 2459.1504
        self.assertAlmostEqual(it.custom_total_, 2459.1504, places=1)

        # customs = 0
        self.assertAlmostEqual(it.custom_customs_value, 0, places=2)

        # selling = 2459.15
        self.assertAlmostEqual(it.custom_selling_price, 2459.15, places=0)

        # cogs = base + incentive + customs = 1229.58
        self.assertAlmostEqual(it.custom_cogs, 1229.58, places=0)

        # margin% = 50%
        self.assertAlmostEqual(it.custom_margin_, 50.0, places=0)

        # rate = selling / qty
        self.assertAlmostEqual(it.rate, 2459.15 / 2, places=0)

    def test_example2_qty1_customs1(self):
        """Row 85-88: Std=271.73, Spl=250, Ship=20%, Fin=2%, Trans=1.5%,
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

        # incentive = 5% * 317.17 = 15.86
        self.assertAlmostEqual(it.custom_incentive_value, 15.86, places=1)

        # markup = 21% * 333.03 = 69.94
        self.assertAlmostEqual(it.custom_markup_value, 69.94, places=1)

        # total = 402.97
        self.assertAlmostEqual(it.custom_total_, 402.97, places=1)

        # customs = 1% * 402.97 = 4.03
        self.assertAlmostEqual(it.custom_customs_value, 4.03, places=1)

        # selling = 407.00
        self.assertAlmostEqual(it.custom_selling_price, 407.0, places=0)

        # cogs = 317.17 + 15.86 + 4.03 = 337.06
        self.assertAlmostEqual(it.custom_cogs, 337.06, places=1)

        # margin% = 17.18%
        self.assertAlmostEqual(it.custom_margin_, 17.18, places=0)

    def test_example3_qty1_customs1_lower_markup(self):
        """Row 95-98: Std=160, Spl=140, Ship=20%, Fin=2%, Trans=1.5%,
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

        self.assertAlmostEqual(it.custom_incentive_value, 5.38, places=1)
        self.assertAlmostEqual(it.custom_markup_value, 27.70, places=1)
        self.assertAlmostEqual(it.custom_total_, 212.38, places=1)
        self.assertAlmostEqual(it.custom_customs_value, 2.12, places=1)
        self.assertAlmostEqual(it.custom_selling_price, 214.50, places=0)
        self.assertAlmostEqual(it.custom_cogs, 186.80, places=0)
        self.assertAlmostEqual(it.custom_margin_, 12.91, places=0)


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
    """Verify incentive distribution logic."""

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

        # Incentive should be distributed proportional to cogs
        total_cogs_before = it1.custom_cogs + it2.custom_cogs
        # After distribution, selling should increase by markup on the extra incentive...
        # but actually distribute_incentive_server adds incentive to cogs and keeps markup fixed.
        # So selling = adjusted_cogs + original_markup

        # Just verify incentive values sum to total
        total_distributed = it1.custom_incentive_value + it2.custom_incentive_value
        self.assertAlmostEqual(total_distributed, total_incentive, places=2)


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

        # After pipeline: item should be calculated, totals set
        self.assertAlmostEqual(it1.custom_selling_price, 2459.15, places=0)
        self.assertAlmostEqual(doc.custom_total_selling_new, 2459.15, places=0)
        self.assertAlmostEqual(doc.custom_total_margin_percent_new, 50.0, places=0)


if __name__ == "__main__":
    unittest.main()
