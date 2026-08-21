"""
Tests for the Landed Cost Voucher rounding-residue relocation
(_lcv_move_residue_off_zero_basis_items).

LCV-FZCO-26-00218 (Avientek FZCO): a freight LCV distributed "based on
Amount" across two receipts; one receipt's items were all zero-amount
(free lines). ERPNext dumps the distribution rounding residue onto the
LAST item, which was one of those zero-amount lines, giving that receipt
a -0.02 charge with no real cost. Its stock revaluation then produced a
single-account GL map, which erpnext.accounts.general_ledger.make_gl_entries
rejects ("Incorrect number of General Ledger Entries found").

The patch re-homes any residue stranded on a zero-basis item onto the
item that already carries the largest real charge, so a fully-zero-basis
receipt stays at exactly 0 (empty GL, no error) and the total is conserved.

Pure-function style — no site needed.
"""
import unittest

from avientek import _lcv_move_residue_off_zero_basis_items


class FakeItem(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)

    def precision(self, _field):
        return 2

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v


class FakeDoc:
    def __init__(self, based_on="Amount", taxes=True, items=None):
        self.distribute_charges_based_on = based_on
        self._taxes = [1] if taxes else []
        self.items = items or []

    def get(self, k, default=None):
        if k == "taxes":
            return self._taxes
        if k == "distribute_charges_based_on":
            return self.distribute_charges_based_on
        if k == "items":
            return self.items
        return default


def _amt_item(amount, applicable_charges):
    return FakeItem(amount=amount, applicable_charges=applicable_charges)


class TestLcvResidueRelocation(unittest.TestCase):
    def test_residue_moves_off_zero_amount_item(self):
        # Two real lines carrying the charge, one free line that wrongly
        # holds the -0.02 rounding residue.
        real1 = _amt_item(1000.0, 36269.02)
        free = _amt_item(0.0, -0.02)
        doc = FakeDoc(items=[real1, free])
        _lcv_move_residue_off_zero_basis_items(doc)
        self.assertEqual(free.applicable_charges, 0.0)          # free line cleared
        self.assertEqual(real1.applicable_charges, 36269.0)      # residue absorbed
        self.assertEqual(
            round(real1.applicable_charges + free.applicable_charges, 2), 36269.0
        )  # total conserved

    def test_multiple_zero_basis_items_all_cleared(self):
        real = _amt_item(500.0, 494.03)
        z1 = _amt_item(0.0, -0.01)
        z2 = _amt_item(0.0, -0.01)
        doc = FakeDoc(items=[real, z1, z2])
        _lcv_move_residue_off_zero_basis_items(doc)
        self.assertEqual(z1.applicable_charges, 0.0)
        self.assertEqual(z2.applicable_charges, 0.0)
        self.assertEqual(real.applicable_charges, 494.01)

    def test_normal_lcv_is_untouched(self):
        # All lines have a non-zero basis: nothing to move.
        a = _amt_item(100.0, 60.0)
        b = _amt_item(50.0, 40.0)
        doc = FakeDoc(items=[a, b])
        _lcv_move_residue_off_zero_basis_items(doc)
        self.assertEqual(a.applicable_charges, 60.0)
        self.assertEqual(b.applicable_charges, 40.0)

    def test_zero_basis_item_with_zero_charge_is_noop(self):
        # A free line that correctly holds 0 charge — nothing to do.
        a = _amt_item(100.0, 100.0)
        free = _amt_item(0.0, 0.0)
        doc = FakeDoc(items=[a, free])
        _lcv_move_residue_off_zero_basis_items(doc)
        self.assertEqual(a.applicable_charges, 100.0)
        self.assertEqual(free.applicable_charges, 0.0)

    def test_distribute_manually_is_skipped(self):
        # Manual distribution must not be touched.
        free = _amt_item(0.0, 5.0)
        doc = FakeDoc(based_on="Distribute Manually", items=[_amt_item(100.0, 95.0), free])
        _lcv_move_residue_off_zero_basis_items(doc)
        self.assertEqual(free.applicable_charges, 5.0)  # unchanged

    def test_no_taxes_is_skipped(self):
        free = _amt_item(0.0, -0.02)
        doc = FakeDoc(taxes=False, items=[_amt_item(100.0, 100.0), free])
        _lcv_move_residue_off_zero_basis_items(doc)
        self.assertEqual(free.applicable_charges, -0.02)  # unchanged

    def test_qty_basis_also_handled(self):
        # Same defect can occur with "Qty" distribution and a zero-qty line.
        real = _amt_item(0, 0)  # amount unused
        real.qty = 10.0
        real.applicable_charges = 100.02
        z = _amt_item(0, 0)
        z.qty = 0.0
        z.applicable_charges = -0.02
        doc = FakeDoc(based_on="Qty", items=[real, z])
        _lcv_move_residue_off_zero_basis_items(doc)
        self.assertEqual(z.applicable_charges, 0.0)
        self.assertEqual(real.applicable_charges, 100.0)


if __name__ == "__main__":
    unittest.main()
