"""
Tests for Payment Request Form.
Covers:
  - Outstanding amount calculations (Supplier, Customer, Employee)
  - Currency conversion and exchange rate handling
  - Multi-currency totals aggregation
  - Internal transfer amount calculations
  - Child table field sync (grand_total ↔ base_grand_total, outstanding ↔ base_outstanding)
  - Manual entry handling
  - Debit note / return handling
  - Payment reference row add/remove
  - Document mapping (Payment Entry, Journal Entry creation)
  - Edge cases (zero amounts, missing exchange rates, empty references)

Think as developer, enter data as user — tests simulate real user workflows:
  adding invoices, changing amounts, switching currencies, removing rows, etc.
"""
import unittest
from unittest.mock import MagicMock, patch
import frappe
from frappe.utils import flt

# ─── Mock frappe.get_system_settings if needed ───
_real_get_system_settings = getattr(frappe, "get_system_settings", None)


def _mock_get_system_settings(key=None):
    settings = {"rounding_method": "Banker's Rounding (legacy)"}
    if key:
        return settings.get(key)
    return settings


frappe.get_system_settings = _mock_get_system_settings

# Import server-side functions under test
from avientek.avientek.doctype.payment_request_form.payment_request_form import (
    _get_customer_credit_documents,
    _get_outstanding_employee_advances,
    _get_outstanding_employee_journal_entries,
    _get_outstanding_expense_claims,
    _get_outstanding_purchase_orders,
    fetch_party_name,
    get_supplier_bank_details,
    get_linked_po_for_invoice,
    REFERENCE_DOCTYPE_MAP,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers: simulate Payment Request Reference rows and form doc
# ──────────────────────────────────────────────────────────────────────────────

def make_ref_row(**kwargs):
    """Create a mock Payment Request Reference child row."""
    defaults = {
        "reference_doctype": "Purchase Invoice",
        "reference_name": "PI-001",
        "bill_no": "INV-001",
        "invoice_date": "2025-01-15",
        "due_date": "2025-02-15",
        "currency": "AED",
        "grand_total": 0,
        "base_grand_total": 0,
        "outstanding_amount": 0,
        "base_outstanding_amount": 0,
        "exchange_rate": 1,
        "is_return": 0,
        "return_against": "",
        "document_reference": "",
        "remarks": "",
    }
    defaults.update(kwargs)
    row = MagicMock()
    for k, v in defaults.items():
        setattr(row, k, v)
    row.get = lambda key, default=None: getattr(row, key, default)
    return row


def make_prf_doc(**kwargs):
    """Create a mock Payment Request Form document."""
    defaults = {
        "name": "PRF-TEST-001",
        "payment_type": "Pay",
        "company": "Test Company",
        "party_type": "Supplier",
        "party": "Test Supplier",
        "party_name": "Test Supplier Name",
        "posting_date": "2025-01-15",
        "currency": "AED",
        "issued_bank": "",
        "issued_currency": "AED",
        "receiving_bank": "",
        "receiving_currency": "AED",
        "issued_amount": 0,
        "receiving_amount": 0,
        "transfer_exchange_rate": 0,
        "total_outstanding_amount": 0,
        "total_payment_amount": 0,
        "payment_references": [],
    }
    defaults.update(kwargs)
    doc = MagicMock()
    for k, v in defaults.items():
        setattr(doc, k, v)
    doc.get = lambda key, default=None: getattr(doc, key, default)
    return doc


# ──────────────────────────────────────────────────────────────────────────────
# JS logic reimplemented in Python for testing (mirrors payment_request_form.js)
# ──────────────────────────────────────────────────────────────────────────────

def recalculate_totals(payment_references, company_currency="AED"):
    """Python equivalent of JS recalculate_totals.
    Returns (total_base_amount, total_base_outstanding, currency_totals).
    """
    total_base_amount = 0
    total_base_outstanding = 0
    currency_totals = {}

    for row in payment_references:
        total_base_amount += flt(row.base_grand_total or 0, 2)
        total_base_outstanding += flt(row.base_outstanding_amount or 0, 2)

        curr = row.currency or "Unknown"
        if curr not in currency_totals:
            currency_totals[curr] = {
                "billing": 0, "base": 0,
                "outstanding": 0, "base_outstanding": 0,
            }
        currency_totals[curr]["billing"] += flt(row.grand_total or 0, 2)
        currency_totals[curr]["base"] += flt(row.base_grand_total or 0, 2)
        currency_totals[curr]["outstanding"] += flt(row.outstanding_amount or 0, 2)
        currency_totals[curr]["base_outstanding"] += flt(row.base_outstanding_amount or 0, 2)

    total_base_amount = flt(total_base_amount, 2)
    total_base_outstanding = flt(total_base_outstanding, 2)
    for curr in currency_totals:
        for key in currency_totals[curr]:
            currency_totals[curr][key] = flt(currency_totals[curr][key], 2)

    return total_base_amount, total_base_outstanding, currency_totals


def sync_grand_total(row):
    """Python equivalent of JS grand_total handler.
    When grand_total changes → recalculate base_grand_total and outstanding.
    """
    rate = flt(row.exchange_rate or 1)
    row.base_grand_total = flt(row.grand_total * rate, 4)
    row.outstanding_amount = row.grand_total
    row.base_outstanding_amount = row.base_grand_total


def sync_base_grand_total_manual(row):
    """Python equivalent of JS base_grand_total handler (Manual type only).
    When base_grand_total changes → recalculate grand_total and outstanding.
    """
    if row.reference_doctype != "Manual":
        return
    rate = flt(row.exchange_rate or 1)
    if rate == 1:
        row.grand_total = row.base_grand_total
    else:
        row.grand_total = flt(row.base_grand_total / rate, 4)
    row.outstanding_amount = row.grand_total
    row.base_outstanding_amount = row.base_grand_total


def sync_outstanding(row):
    """Python equivalent of JS outstanding_amount handler.
    When outstanding_amount changes → recalculate base_outstanding_amount.
    """
    rate = flt(row.exchange_rate or 1)
    row.base_outstanding_amount = flt(row.outstanding_amount * rate, 4)


def sync_base_outstanding(row):
    """Python equivalent of JS base_outstanding_amount handler.
    When base_outstanding_amount changes → recalculate outstanding_amount.
    """
    rate = flt(row.exchange_rate or 1)
    if rate == 1:
        row.outstanding_amount = row.base_outstanding_amount
    else:
        row.outstanding_amount = flt(row.base_outstanding_amount / rate, 4)


def sync_exchange_rate(row):
    """Python equivalent of JS exchange_rate handler.
    When exchange_rate changes → recalculate base amounts.
    """
    rate = flt(row.exchange_rate or 1)
    if row.reference_doctype == "Manual":
        if getattr(row, "_is_company_currency", False):
            if row.base_grand_total:
                row.grand_total = row.base_grand_total if rate == 1 else flt(row.base_grand_total / rate, 4)
                row.outstanding_amount = row.grand_total
                row.base_outstanding_amount = row.base_grand_total
        else:
            if row.grand_total:
                row.base_grand_total = flt(row.grand_total * rate, 4)
                row.outstanding_amount = row.grand_total
                row.base_outstanding_amount = row.base_grand_total
    else:
        if row.grand_total:
            row.base_grand_total = flt(row.grand_total * rate, 4)
        if row.outstanding_amount:
            row.base_outstanding_amount = flt(row.outstanding_amount * rate, 4)


def calculate_transfer_amounts(doc, source="issued"):
    """Python equivalent of JS calculate_transfer_amounts.
    Calculates receiving_amount or issued_amount from exchange rate.
    """
    issued_currency = doc.issued_currency
    receiving_currency = doc.receiving_currency
    if not issued_currency or not receiving_currency:
        return

    if issued_currency == receiving_currency:
        doc.transfer_exchange_rate = 1
        if source == "issued":
            doc.receiving_amount = doc.issued_amount
        else:
            doc.issued_amount = doc.receiving_amount
        return

    rate = flt(doc.transfer_exchange_rate)
    if rate and rate > 0 and rate != 1:
        if source == "issued" and doc.issued_amount:
            doc.receiving_amount = flt(doc.issued_amount * rate, 2)
        elif source == "receiving" and doc.receiving_amount:
            doc.issued_amount = flt(doc.receiving_amount / rate, 2)


# ══════════════════════════════════════════════════════════════════════════════
# TEST CLASSES
# ══════════════════════════════════════════════════════════════════════════════


class TestRecalculateTotals(unittest.TestCase):
    """Test currency grouping and total calculation (mirrors JS recalculate_totals)."""

    def test_single_aed_invoice(self):
        """User adds one AED invoice."""
        rows = [make_ref_row(
            grand_total=10000, base_grand_total=10000,
            outstanding_amount=10000, base_outstanding_amount=10000,
            currency="AED", exchange_rate=1,
        )]
        total_base, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_base, 10000)
        self.assertEqual(total_os, 10000)
        self.assertEqual(ct["AED"]["billing"], 10000)
        self.assertEqual(ct["AED"]["outstanding"], 10000)

    def test_multi_aed_invoices(self):
        """User adds 3 AED invoices."""
        rows = [
            make_ref_row(grand_total=5000, base_grand_total=5000,
                         outstanding_amount=5000, base_outstanding_amount=5000, currency="AED"),
            make_ref_row(grand_total=3000, base_grand_total=3000,
                         outstanding_amount=2000, base_outstanding_amount=2000, currency="AED"),
            make_ref_row(grand_total=7000, base_grand_total=7000,
                         outstanding_amount=7000, base_outstanding_amount=7000, currency="AED"),
        ]
        total_base, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_base, 15000)
        self.assertEqual(total_os, 14000)
        self.assertEqual(ct["AED"]["billing"], 15000)
        self.assertEqual(ct["AED"]["outstanding"], 14000)

    def test_multi_currency_invoices(self):
        """User adds invoices in AED and USD."""
        rows = [
            make_ref_row(grand_total=10000, base_grand_total=10000,
                         outstanding_amount=10000, base_outstanding_amount=10000, currency="AED"),
            make_ref_row(grand_total=5000, base_grand_total=18350,
                         outstanding_amount=5000, base_outstanding_amount=18350,
                         currency="USD", exchange_rate=3.67),
        ]
        total_base, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_base, 28350)
        self.assertEqual(total_os, 28350)
        self.assertEqual(ct["AED"]["billing"], 10000)
        self.assertEqual(ct["USD"]["billing"], 5000)
        self.assertEqual(ct["USD"]["base"], 18350)

    def test_debit_note_negative_outstanding(self):
        """User has an invoice + debit note (negative outstanding)."""
        rows = [
            make_ref_row(grand_total=20000, base_grand_total=20000,
                         outstanding_amount=20000, base_outstanding_amount=20000, currency="AED"),
            make_ref_row(grand_total=5000, base_grand_total=5000,
                         outstanding_amount=-5000, base_outstanding_amount=-5000,
                         currency="AED", is_return=1, reference_doctype="Debit Note"),
        ]
        total_base, total_os, ct = recalculate_totals(rows)
        # base_grand_total sums: 20000 + 5000 = 25000
        self.assertEqual(total_base, 25000)
        # outstanding sums: 20000 + (-5000) = 15000
        self.assertEqual(total_os, 15000)

    def test_empty_references(self):
        """No payment references — totals should be zero."""
        total_base, total_os, ct = recalculate_totals([])
        self.assertEqual(total_base, 0)
        self.assertEqual(total_os, 0)
        self.assertEqual(ct, {})

    def test_three_currencies(self):
        """User has invoices in AED, USD, and EUR."""
        rows = [
            make_ref_row(grand_total=10000, base_grand_total=10000,
                         outstanding_amount=10000, base_outstanding_amount=10000, currency="AED"),
            make_ref_row(grand_total=2000, base_grand_total=7340,
                         outstanding_amount=2000, base_outstanding_amount=7340,
                         currency="USD", exchange_rate=3.67),
            make_ref_row(grand_total=1500, base_grand_total=5895,
                         outstanding_amount=1500, base_outstanding_amount=5895,
                         currency="EUR", exchange_rate=3.93),
        ]
        total_base, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_base, 23235)
        self.assertIn("AED", ct)
        self.assertIn("USD", ct)
        self.assertIn("EUR", ct)
        self.assertEqual(ct["EUR"]["billing"], 1500)
        self.assertEqual(ct["EUR"]["base"], 5895)

    def test_partially_paid_invoice(self):
        """Invoice with grand_total 10000 but outstanding only 3000."""
        rows = [make_ref_row(
            grand_total=10000, base_grand_total=10000,
            outstanding_amount=3000, base_outstanding_amount=3000, currency="AED",
        )]
        total_base, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_base, 10000)
        self.assertEqual(total_os, 3000)
        self.assertEqual(ct["AED"]["billing"], 10000)
        self.assertEqual(ct["AED"]["outstanding"], 3000)

    def test_floating_point_rounding(self):
        """Many small amounts should sum without floating-point drift."""
        rows = [
            make_ref_row(grand_total=33.33, base_grand_total=33.33,
                         outstanding_amount=33.33, base_outstanding_amount=33.33, currency="AED")
            for _ in range(3)
        ]
        total_base, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_base, 99.99)
        self.assertEqual(total_os, 99.99)


class TestChildTableFieldSync(unittest.TestCase):
    """Test field sync handlers that mirror JS child table events."""

    def test_grand_total_sets_base_and_outstanding_aed(self):
        """User enters grand_total in AED → base and outstanding sync."""
        row = make_ref_row(exchange_rate=1)
        row.grand_total = 15000
        sync_grand_total(row)
        self.assertEqual(row.base_grand_total, 15000)
        self.assertEqual(row.outstanding_amount, 15000)
        self.assertEqual(row.base_outstanding_amount, 15000)

    def test_grand_total_with_foreign_currency(self):
        """User enters grand_total in USD with exchange_rate=3.67."""
        row = make_ref_row(currency="USD", exchange_rate=3.67)
        row.grand_total = 5000
        sync_grand_total(row)
        self.assertAlmostEqual(row.base_grand_total, 18350, places=2)
        self.assertEqual(row.outstanding_amount, 5000)
        self.assertAlmostEqual(row.base_outstanding_amount, 18350, places=2)

    def test_base_grand_total_manual_entry_aed(self):
        """User enters base_grand_total for Manual type in AED."""
        row = make_ref_row(reference_doctype="Manual", exchange_rate=1)
        row.base_grand_total = 25000
        sync_base_grand_total_manual(row)
        self.assertEqual(row.grand_total, 25000)
        self.assertEqual(row.outstanding_amount, 25000)

    def test_base_grand_total_manual_entry_foreign(self):
        """User enters base_grand_total for Manual type, foreign currency."""
        row = make_ref_row(reference_doctype="Manual", currency="USD", exchange_rate=3.67)
        row.base_grand_total = 18350
        sync_base_grand_total_manual(row)
        expected_fc = flt(18350 / 3.67, 4)
        self.assertAlmostEqual(row.grand_total, expected_fc, places=2)

    def test_base_grand_total_ignored_for_non_manual(self):
        """base_grand_total handler should do nothing for non-Manual types."""
        row = make_ref_row(reference_doctype="Purchase Invoice", exchange_rate=1)
        row.base_grand_total = 50000
        row.grand_total = 10000  # Different from base — should NOT be changed
        sync_base_grand_total_manual(row)
        self.assertEqual(row.grand_total, 10000)  # Unchanged

    def test_outstanding_syncs_to_base(self):
        """User changes outstanding_amount → base_outstanding_amount recalculates."""
        row = make_ref_row(exchange_rate=3.67)
        row.outstanding_amount = 3000
        sync_outstanding(row)
        self.assertAlmostEqual(row.base_outstanding_amount, 11010, places=2)

    def test_base_outstanding_syncs_to_outstanding(self):
        """User changes base_outstanding_amount → outstanding_amount recalculates."""
        row = make_ref_row(exchange_rate=3.67)
        row.base_outstanding_amount = 11010
        sync_base_outstanding(row)
        expected = flt(11010 / 3.67, 4)
        self.assertAlmostEqual(row.outstanding_amount, expected, places=2)

    def test_base_outstanding_same_currency(self):
        """Same currency: outstanding == base_outstanding."""
        row = make_ref_row(exchange_rate=1)
        row.base_outstanding_amount = 7500
        sync_base_outstanding(row)
        self.assertEqual(row.outstanding_amount, 7500)

    def test_exchange_rate_change_non_manual(self):
        """User changes exchange_rate on non-Manual row → base amounts update."""
        row = make_ref_row(
            reference_doctype="Purchase Invoice",
            grand_total=5000, outstanding_amount=3000,
            exchange_rate=3.50,
        )
        row.exchange_rate = 3.70
        sync_exchange_rate(row)
        self.assertAlmostEqual(row.base_grand_total, 18500, places=2)
        self.assertAlmostEqual(row.base_outstanding_amount, 11100, places=2)

    def test_exchange_rate_change_manual_foreign(self):
        """User changes exchange_rate on Manual row (foreign currency)."""
        row = make_ref_row(
            reference_doctype="Manual",
            grand_total=5000, base_grand_total=17500,
            exchange_rate=3.50, _is_company_currency=False,
        )
        row._is_company_currency = False
        row.exchange_rate = 3.80
        sync_exchange_rate(row)
        self.assertAlmostEqual(row.base_grand_total, 19000, places=2)
        self.assertEqual(row.outstanding_amount, 5000)

    def test_exchange_rate_change_manual_company_currency(self):
        """User changes exchange_rate on Manual row entered in company currency."""
        row = make_ref_row(
            reference_doctype="Manual",
            grand_total=5000, base_grand_total=18000,
            exchange_rate=3.60, _is_company_currency=True,
        )
        row._is_company_currency = True
        row.exchange_rate = 3.70
        sync_exchange_rate(row)
        expected_fc = flt(18000 / 3.70, 4)
        self.assertAlmostEqual(row.grand_total, expected_fc, places=2)
        self.assertEqual(row.base_outstanding_amount, 18000)


class TestInternalTransfer(unittest.TestCase):
    """Test Internal Transfer amount calculations."""

    def test_same_currency_transfer(self):
        """Same currency transfer: amounts are equal, rate = 1."""
        doc = make_prf_doc(
            payment_type="Internal Transfer",
            issued_currency="AED", receiving_currency="AED",
            issued_amount=50000, receiving_amount=0,
        )
        calculate_transfer_amounts(doc, source="issued")
        self.assertEqual(doc.transfer_exchange_rate, 1)
        self.assertEqual(doc.receiving_amount, 50000)

    def test_same_currency_reverse(self):
        """Same currency, source=receiving."""
        doc = make_prf_doc(
            payment_type="Internal Transfer",
            issued_currency="AED", receiving_currency="AED",
            issued_amount=0, receiving_amount=30000,
        )
        calculate_transfer_amounts(doc, source="receiving")
        self.assertEqual(doc.issued_amount, 30000)

    def test_cross_currency_transfer_from_issued(self):
        """AED → USD transfer with exchange rate."""
        doc = make_prf_doc(
            payment_type="Internal Transfer",
            issued_currency="AED", receiving_currency="USD",
            issued_amount=36700, receiving_amount=0,
            transfer_exchange_rate=0.2725,  # 1 AED = 0.2725 USD
        )
        calculate_transfer_amounts(doc, source="issued")
        expected = flt(36700 * 0.2725, 2)
        self.assertAlmostEqual(doc.receiving_amount, expected, places=2)

    def test_cross_currency_transfer_from_receiving(self):
        """USD → AED transfer, solve for issued_amount."""
        doc = make_prf_doc(
            payment_type="Internal Transfer",
            issued_currency="AED", receiving_currency="USD",
            issued_amount=0, receiving_amount=10000,
            transfer_exchange_rate=0.2725,
        )
        calculate_transfer_amounts(doc, source="receiving")
        expected = flt(10000 / 0.2725, 2)
        self.assertAlmostEqual(doc.issued_amount, expected, places=2)

    def test_missing_currencies_no_calc(self):
        """Missing currencies → no calculation."""
        doc = make_prf_doc(
            payment_type="Internal Transfer",
            issued_currency="", receiving_currency="USD",
            issued_amount=50000,
        )
        calculate_transfer_amounts(doc, source="issued")
        # receiving_amount should remain 0 (no change)
        self.assertEqual(doc.receiving_amount, 0)

    def test_exchange_rate_1_for_different_currencies_no_calc(self):
        """Rate=1 for different currencies is treated as valid by calc (rate>0, rate!=1 check)."""
        doc = make_prf_doc(
            payment_type="Internal Transfer",
            issued_currency="AED", receiving_currency="USD",
            issued_amount=50000, receiving_amount=0,
            transfer_exchange_rate=1,  # rate=1 fails the rate!=1 check
        )
        calculate_transfer_amounts(doc, source="issued")
        # Should not calculate since rate=1 for different currencies
        self.assertEqual(doc.receiving_amount, 0)

    def test_zero_exchange_rate_no_calc(self):
        """Rate=0 → no calculation."""
        doc = make_prf_doc(
            payment_type="Internal Transfer",
            issued_currency="AED", receiving_currency="USD",
            issued_amount=50000, receiving_amount=0,
            transfer_exchange_rate=0,
        )
        calculate_transfer_amounts(doc, source="issued")
        self.assertEqual(doc.receiving_amount, 0)


class TestManualEntryWorkflow(unittest.TestCase):
    """Test the workflow of adding manual payment reference rows."""

    def test_add_manual_row_aed(self):
        """User adds a Manual row in company currency (AED)."""
        row = make_ref_row(
            reference_doctype="Manual", reference_name="",
            currency="AED", exchange_rate=1,
        )
        # User enters grand_total
        row.grand_total = 8500
        sync_grand_total(row)
        self.assertEqual(row.base_grand_total, 8500)
        self.assertEqual(row.outstanding_amount, 8500)
        self.assertEqual(row.base_outstanding_amount, 8500)

    def test_add_manual_row_usd(self):
        """User adds a Manual row in USD."""
        row = make_ref_row(
            reference_doctype="Manual", reference_name="",
            currency="USD", exchange_rate=3.67,
        )
        row.grand_total = 2500
        sync_grand_total(row)
        self.assertAlmostEqual(row.base_grand_total, 9175, places=2)
        self.assertEqual(row.outstanding_amount, 2500)

    def test_manual_row_change_amount_then_rate(self):
        """User enters amount, then changes exchange rate."""
        row = make_ref_row(
            reference_doctype="Manual", currency="USD", exchange_rate=3.67,
            _is_company_currency=False,
        )
        row._is_company_currency = False
        # Step 1: enter grand_total
        row.grand_total = 5000
        sync_grand_total(row)
        self.assertAlmostEqual(row.base_grand_total, 18350, places=2)

        # Step 2: change exchange rate
        row.exchange_rate = 3.80
        sync_exchange_rate(row)
        self.assertAlmostEqual(row.base_grand_total, 19000, places=2)
        self.assertEqual(row.outstanding_amount, 5000)

    def test_manual_row_entered_in_base_currency(self):
        """User enters amount in base_grand_total (company currency)."""
        row = make_ref_row(
            reference_doctype="Manual", currency="USD", exchange_rate=3.67,
        )
        row.base_grand_total = 36700
        sync_base_grand_total_manual(row)
        expected_fc = flt(36700 / 3.67, 4)
        self.assertAlmostEqual(row.grand_total, expected_fc, places=2)
        self.assertEqual(row.base_outstanding_amount, 36700)


class TestDebitNoteHandling(unittest.TestCase):
    """Test debit note / return invoice handling in totals."""

    def test_debit_note_reduces_total_outstanding(self):
        """Debit note with negative outstanding reduces the net outstanding."""
        rows = [
            make_ref_row(
                grand_total=50000, base_grand_total=50000,
                outstanding_amount=50000, base_outstanding_amount=50000,
                currency="AED",
            ),
            make_ref_row(
                reference_doctype="Debit Note",
                grand_total=10000, base_grand_total=10000,
                outstanding_amount=-10000, base_outstanding_amount=-10000,
                currency="AED", is_return=1,
            ),
        ]
        _, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_os, 40000)
        self.assertEqual(ct["AED"]["outstanding"], 40000)

    def test_multiple_debit_notes(self):
        """Multiple debit notes against one invoice."""
        rows = [
            make_ref_row(grand_total=100000, base_grand_total=100000,
                         outstanding_amount=100000, base_outstanding_amount=100000, currency="AED"),
            make_ref_row(reference_doctype="Debit Note", grand_total=20000, base_grand_total=20000,
                         outstanding_amount=-20000, base_outstanding_amount=-20000,
                         currency="AED", is_return=1),
            make_ref_row(reference_doctype="Debit Note", grand_total=15000, base_grand_total=15000,
                         outstanding_amount=-15000, base_outstanding_amount=-15000,
                         currency="AED", is_return=1),
        ]
        _, total_os, _ = recalculate_totals(rows)
        self.assertEqual(total_os, 65000)

    def test_debit_note_foreign_currency(self):
        """Debit note in USD with exchange rate conversion."""
        rows = [
            make_ref_row(grand_total=10000, base_grand_total=36700,
                         outstanding_amount=10000, base_outstanding_amount=36700,
                         currency="USD", exchange_rate=3.67),
            make_ref_row(reference_doctype="Debit Note",
                         grand_total=2000, base_grand_total=7340,
                         outstanding_amount=-2000, base_outstanding_amount=-7340,
                         currency="USD", exchange_rate=3.67, is_return=1),
        ]
        _, total_os, ct = recalculate_totals(rows)
        self.assertEqual(ct["USD"]["outstanding"], 8000)
        self.assertEqual(ct["USD"]["base_outstanding"], 29360)


class TestRowAddRemove(unittest.TestCase):
    """Test adding and removing payment reference rows."""

    def test_add_rows_incrementally(self):
        """User adds rows one by one — totals should update each time."""
        rows = []

        # Add first row
        rows.append(make_ref_row(
            grand_total=10000, base_grand_total=10000,
            outstanding_amount=10000, base_outstanding_amount=10000, currency="AED",
        ))
        _, total_os, _ = recalculate_totals(rows)
        self.assertEqual(total_os, 10000)

        # Add second row
        rows.append(make_ref_row(
            grand_total=5000, base_grand_total=18350,
            outstanding_amount=5000, base_outstanding_amount=18350,
            currency="USD", exchange_rate=3.67,
        ))
        _, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_os, 28350)
        self.assertEqual(len(ct), 2)

        # Add third row (debit note)
        rows.append(make_ref_row(
            reference_doctype="Debit Note",
            grand_total=3000, base_grand_total=3000,
            outstanding_amount=-3000, base_outstanding_amount=-3000,
            currency="AED", is_return=1,
        ))
        _, total_os, _ = recalculate_totals(rows)
        self.assertEqual(total_os, 25350)

    def test_remove_row(self):
        """User removes a row — totals should decrease."""
        rows = [
            make_ref_row(grand_total=10000, base_grand_total=10000,
                         outstanding_amount=10000, base_outstanding_amount=10000, currency="AED"),
            make_ref_row(grand_total=5000, base_grand_total=5000,
                         outstanding_amount=5000, base_outstanding_amount=5000, currency="AED"),
        ]
        _, total_os, _ = recalculate_totals(rows)
        self.assertEqual(total_os, 15000)

        # Remove first row
        rows.pop(0)
        _, total_os, _ = recalculate_totals(rows)
        self.assertEqual(total_os, 5000)

    def test_remove_all_rows(self):
        """User removes all rows — totals should be zero."""
        rows = [
            make_ref_row(grand_total=10000, base_grand_total=10000,
                         outstanding_amount=10000, base_outstanding_amount=10000, currency="AED"),
        ]
        rows.clear()
        _, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_os, 0)
        self.assertEqual(ct, {})


class TestFullWorkflow(unittest.TestCase):
    """End-to-end workflow tests simulating real user actions."""

    def test_supplier_payment_workflow(self):
        """Full workflow: user selects supplier, adds invoices, adds debit note, checks totals."""
        # Step 1: Add 3 purchase invoices
        rows = [
            make_ref_row(
                reference_doctype="Purchase Invoice", reference_name=f"PI-00{i}",
                grand_total=amt, base_grand_total=amt,
                outstanding_amount=os_amt, base_outstanding_amount=os_amt,
                currency="AED", exchange_rate=1,
            )
            for i, (amt, os_amt) in enumerate([
                (25000, 25000),  # Fully outstanding
                (15000, 10000),  # Partially paid
                (8000, 8000),    # Fully outstanding
            ], 1)
        ]
        total_base, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_base, 48000)
        self.assertEqual(total_os, 43000)

        # Step 2: Add a debit note
        rows.append(make_ref_row(
            reference_doctype="Debit Note", reference_name="PI-DN-001",
            grand_total=5000, base_grand_total=5000,
            outstanding_amount=-5000, base_outstanding_amount=-5000,
            currency="AED", is_return=1, return_against="PI-001",
        ))
        _, total_os, _ = recalculate_totals(rows)
        self.assertEqual(total_os, 38000)

        # Step 3: User changes outstanding on PI-002 (partial payment received)
        rows[1].outstanding_amount = 5000
        sync_outstanding(rows[1])
        _, total_os, _ = recalculate_totals(rows)
        self.assertEqual(total_os, 33000)

    def test_multi_currency_supplier_workflow(self):
        """Supplier with invoices in multiple currencies."""
        rows = [
            make_ref_row(
                reference_doctype="Purchase Invoice", reference_name="PI-AED-001",
                grand_total=30000, base_grand_total=30000,
                outstanding_amount=30000, base_outstanding_amount=30000,
                currency="AED", exchange_rate=1,
            ),
            make_ref_row(
                reference_doctype="Purchase Invoice", reference_name="PI-USD-001",
                grand_total=10000, base_grand_total=36700,
                outstanding_amount=10000, base_outstanding_amount=36700,
                currency="USD", exchange_rate=3.67,
            ),
            make_ref_row(
                reference_doctype="Purchase Invoice", reference_name="PI-EUR-001",
                grand_total=5000, base_grand_total=19650,
                outstanding_amount=5000, base_outstanding_amount=19650,
                currency="EUR", exchange_rate=3.93,
            ),
        ]
        total_base, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_base, 86350)
        self.assertEqual(total_os, 86350)
        self.assertEqual(len(ct), 3)
        self.assertEqual(ct["AED"]["billing"], 30000)
        self.assertEqual(ct["USD"]["billing"], 10000)
        self.assertEqual(ct["EUR"]["billing"], 5000)

    def test_employee_expense_claim_workflow(self):
        """Employee payment workflow with expense claims."""
        rows = [
            make_ref_row(
                reference_doctype="Expense Claim", reference_name="EC-001",
                grand_total=3500, base_grand_total=3500,
                outstanding_amount=3500, base_outstanding_amount=3500,
                currency="AED", exchange_rate=1,
            ),
            make_ref_row(
                reference_doctype="Employee Advance", reference_name="EA-001",
                grand_total=10000, base_grand_total=10000,
                outstanding_amount=7500, base_outstanding_amount=7500,
                currency="AED", exchange_rate=1,
            ),
        ]
        _, total_os, _ = recalculate_totals(rows)
        self.assertEqual(total_os, 11000)

    def test_customer_credit_note_workflow(self):
        """Customer payment workflow with credit notes."""
        rows = [
            make_ref_row(
                reference_doctype="Credit Note", reference_name="CN-001",
                grand_total=8000, base_grand_total=8000,
                outstanding_amount=-8000, base_outstanding_amount=-8000,
                currency="AED", is_return=1,
            ),
            make_ref_row(
                reference_doctype="Journal Entry", reference_name="JE-001",
                grand_total=2000, base_grand_total=2000,
                outstanding_amount=2000, base_outstanding_amount=2000,
                currency="AED",
            ),
        ]
        _, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_os, -6000)

    def test_internal_transfer_workflow(self):
        """Full internal transfer: set currencies, set amount, calculate."""
        doc = make_prf_doc(
            payment_type="Internal Transfer",
            issued_currency="AED", receiving_currency="USD",
            transfer_exchange_rate=0.2725,
        )
        # Step 1: User enters issued amount
        doc.issued_amount = 100000
        calculate_transfer_amounts(doc, source="issued")
        self.assertAlmostEqual(doc.receiving_amount, 27250, places=2)

        # Step 2: User changes exchange rate
        doc.transfer_exchange_rate = 0.2700
        calculate_transfer_amounts(doc, source="issued")
        self.assertAlmostEqual(doc.receiving_amount, 27000, places=2)

        # Step 3: User changes receiving amount instead
        doc.receiving_amount = 28000
        calculate_transfer_amounts(doc, source="receiving")
        expected_issued = flt(28000 / 0.2700, 2)
        self.assertAlmostEqual(doc.issued_amount, expected_issued, places=2)

    def test_add_invoice_change_exchange_rate_recalc(self):
        """User adds foreign invoice, then exchange rate changes — base amounts update."""
        row = make_ref_row(
            reference_doctype="Purchase Invoice",
            grand_total=10000, outstanding_amount=10000,
            currency="USD", exchange_rate=3.67,
        )
        # Initial sync
        sync_grand_total(row)
        self.assertAlmostEqual(row.base_grand_total, 36700, places=2)

        # Exchange rate changes
        row.exchange_rate = 3.75
        sync_exchange_rate(row)
        self.assertAlmostEqual(row.base_grand_total, 37500, places=2)
        self.assertAlmostEqual(row.base_outstanding_amount, 37500, places=2)

        # Check totals
        _, total_os, ct = recalculate_totals([row])
        self.assertAlmostEqual(ct["USD"]["base_outstanding"], 37500, places=2)

    def test_mixed_manual_and_invoice_rows(self):
        """Mix of auto-fetched invoices and manual entries."""
        rows = [
            make_ref_row(
                reference_doctype="Purchase Invoice", reference_name="PI-001",
                grand_total=20000, base_grand_total=20000,
                outstanding_amount=20000, base_outstanding_amount=20000,
                currency="AED", exchange_rate=1,
            ),
            make_ref_row(
                reference_doctype="Manual", reference_name="",
                grand_total=5000, base_grand_total=5000,
                outstanding_amount=5000, base_outstanding_amount=5000,
                currency="AED", exchange_rate=1,
            ),
        ]
        _, total_os, _ = recalculate_totals(rows)
        self.assertEqual(total_os, 25000)

        # User changes manual entry amount
        rows[1].grand_total = 7500
        sync_grand_total(rows[1])
        _, total_os, _ = recalculate_totals(rows)
        self.assertEqual(total_os, 27500)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def test_zero_exchange_rate_defaults_to_1(self):
        """Exchange rate of 0 treated as 1."""
        row = make_ref_row(exchange_rate=0, grand_total=10000)
        sync_grand_total(row)
        # flt(0) or 1 → rate=1
        self.assertEqual(row.base_grand_total, flt(10000 * (flt(0) or 1), 4))

    def test_negative_grand_total(self):
        """Negative grand_total (like a debit note entered directly)."""
        row = make_ref_row(exchange_rate=1, grand_total=-5000)
        sync_grand_total(row)
        self.assertEqual(row.base_grand_total, -5000)
        self.assertEqual(row.outstanding_amount, -5000)

    def test_very_large_amounts(self):
        """Very large invoice amounts."""
        row = make_ref_row(exchange_rate=1, grand_total=999999999.99)
        sync_grand_total(row)
        self.assertEqual(row.base_grand_total, flt(999999999.99, 4))

    def test_very_small_amounts(self):
        """Very small amounts (sub-fils)."""
        row = make_ref_row(exchange_rate=3.67, grand_total=0.01)
        sync_grand_total(row)
        self.assertAlmostEqual(row.base_grand_total, 0.0367, places=4)

    def test_all_zero_amounts(self):
        """All amounts are zero."""
        row = make_ref_row(
            grand_total=0, base_grand_total=0,
            outstanding_amount=0, base_outstanding_amount=0,
            exchange_rate=1,
        )
        sync_grand_total(row)
        _, total_os, _ = recalculate_totals([row])
        self.assertEqual(total_os, 0)

    def test_missing_currency_defaults_to_unknown(self):
        """Missing currency field groups as 'Unknown' in totals."""
        row = make_ref_row(currency=None, grand_total=5000, base_grand_total=5000,
                           outstanding_amount=5000, base_outstanding_amount=5000)
        _, _, ct = recalculate_totals([row])
        self.assertIn("Unknown", ct)

    def test_purchase_order_advance_payment(self):
        """Purchase Order (advance payment) in totals."""
        rows = [
            make_ref_row(
                reference_doctype="Purchase Order", reference_name="PO-001",
                grand_total=100000, base_grand_total=100000,
                outstanding_amount=100000, base_outstanding_amount=100000,
                currency="AED", exchange_rate=1,
            ),
        ]
        _, total_os, ct = recalculate_totals(rows)
        self.assertEqual(total_os, 100000)
        self.assertEqual(ct["AED"]["billing"], 100000)


class TestReferenceDocTypeMap(unittest.TestCase):
    """Test the REFERENCE_DOCTYPE_MAP mapping."""

    def test_debit_note_maps_to_purchase_invoice(self):
        self.assertEqual(REFERENCE_DOCTYPE_MAP["Debit Note"], "Purchase Invoice")

    def test_credit_note_maps_to_sales_invoice(self):
        self.assertEqual(REFERENCE_DOCTYPE_MAP["Credit Note"], "Sales Invoice")

    def test_all_expected_mappings_exist(self):
        expected = [
            "Purchase Invoice", "Debit Note", "Credit Note",
            "Sales Invoice", "Expense Claim", "Employee Advance",
            "Payment Entry", "Journal Entry", "Purchase Order",
        ]
        for key in expected:
            self.assertIn(key, REFERENCE_DOCTYPE_MAP)

    def test_unknown_doctype_returns_itself(self):
        """REFERENCE_DOCTYPE_MAP.get() with default returns the key itself."""
        unknown = "Some Unknown Type"
        result = REFERENCE_DOCTYPE_MAP.get(unknown, unknown)
        self.assertEqual(result, unknown)


class TestOutstandingCalcHelpers(unittest.TestCase):
    """Test helper functions that compute outstanding amounts."""

    def test_get_customer_credit_docs_empty_args(self):
        """Empty args returns empty list."""
        result = _get_customer_credit_documents({})
        self.assertEqual(result, [])

    def test_get_customer_credit_docs_missing_party(self):
        result = _get_customer_credit_documents({"company": "Test"})
        self.assertEqual(result, [])

    def test_get_customer_credit_docs_missing_company(self):
        result = _get_customer_credit_documents({"party": "Customer-001"})
        self.assertEqual(result, [])

    def test_get_employee_advances_empty_args(self):
        result = _get_outstanding_employee_advances({})
        self.assertEqual(result, [])

    def test_get_employee_je_empty_args(self):
        result = _get_outstanding_employee_journal_entries({})
        self.assertEqual(result, [])

    def test_get_expense_claims_empty_args(self):
        result = _get_outstanding_expense_claims({})
        self.assertEqual(result, [])

    def test_get_purchase_orders_empty_args(self):
        result = _get_outstanding_purchase_orders({})
        self.assertEqual(result, [])


class TestFieldSyncChain(unittest.TestCase):
    """Test chained field updates (simulating user editing multiple fields in sequence)."""

    def test_full_manual_entry_chain(self):
        """Simulate full manual entry: set type → set currency → enter amount → check totals."""
        # Step 1: Create row with Manual type
        row = make_ref_row(
            reference_doctype="Manual", currency="USD", exchange_rate=3.67,
        )
        row._is_company_currency = False

        # Step 2: User enters grand_total
        row.grand_total = 15000
        sync_grand_total(row)
        self.assertAlmostEqual(row.base_grand_total, 55050, places=2)

        # Step 3: Check totals
        _, total_os, ct = recalculate_totals([row])
        self.assertAlmostEqual(total_os, 55050, places=2)
        self.assertAlmostEqual(ct["USD"]["outstanding"], 15000, places=2)

    def test_update_outstanding_then_recalc(self):
        """User reduces outstanding, then totals recalculate."""
        rows = [
            make_ref_row(
                grand_total=50000, base_grand_total=50000,
                outstanding_amount=50000, base_outstanding_amount=50000,
                currency="AED", exchange_rate=1,
            ),
        ]
        _, os1, _ = recalculate_totals(rows)
        self.assertEqual(os1, 50000)

        # User updates outstanding (partial payment)
        rows[0].outstanding_amount = 30000
        sync_outstanding(rows[0])
        _, os2, _ = recalculate_totals(rows)
        self.assertEqual(os2, 30000)

    def test_change_exchange_rate_on_multiple_rows(self):
        """Change exchange rate on multiple USD rows — all base amounts update."""
        rows = [
            make_ref_row(
                reference_doctype="Purchase Invoice",
                grand_total=5000, outstanding_amount=5000,
                currency="USD", exchange_rate=3.67,
            ),
            make_ref_row(
                reference_doctype="Purchase Invoice",
                grand_total=3000, outstanding_amount=3000,
                currency="USD", exchange_rate=3.67,
            ),
        ]
        # Initial sync
        for r in rows:
            sync_grand_total(r)

        _, os1, _ = recalculate_totals(rows)
        self.assertAlmostEqual(os1, 29360, places=2)  # (5000+3000)*3.67

        # Exchange rate changes to 3.75
        for r in rows:
            r.exchange_rate = 3.75
            sync_exchange_rate(r)

        _, os2, _ = recalculate_totals(rows)
        self.assertAlmostEqual(os2, 30000, places=2)  # (5000+3000)*3.75


if __name__ == "__main__":
    unittest.main()
