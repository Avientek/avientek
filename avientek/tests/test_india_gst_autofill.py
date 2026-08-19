"""
Tests for the AETPL India GST tax-template autofill.

Covers:
  - Layer 0 (2026-08-19, LTD-26-27-00798): export / SEZ supplies must
    NEVER receive a domestic In-state / Out-state template, however the
    state codes happen to compare.
  - Layers 1-3 still behave as before for genuine domestic supplies.

Pure-function style, same as test_quotation_calc.py — the frappe.db /
frappe.get_doc calls the hook makes are patched, so no site is needed.
"""
import unittest
from unittest.mock import patch

from avientek.events.utils import (
    _AETPL_INDIA,
    _AETPL_INSTATE_TEMPLATE,
    _AETPL_OUTSTATE_TEMPLATE,
    _is_non_domestic_supply,
    autofill_india_sales_taxes_template,
)


class FakeRow(dict):
    """Child-table row that supports both attribute and .get() access."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        self[key] = value


class FakeDoc:
    """Minimal stand-in for a Frappe Document.

    `taxes` is a real list so `_apply_template_rows`'s in-place clear
    (`existing[:] = []`) behaves exactly as it does on a real doc.
    """

    def __init__(self, doctype="Sales Invoice", **fields):
        self.doctype = doctype
        self.taxes = []
        self.__dict__.update(fields)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)

    def append(self, fieldname, row):
        rows = self.__dict__.setdefault(fieldname, [])
        rows.append(FakeRow(row))
        return rows[-1]


def make_export_si(**overrides):
    """Sales Invoice mirroring LTD-26-27-00798 — Spain, zero-rated export."""
    fields = {
        "company": _AETPL_INDIA,
        "customer": "C-AETPL-00837",
        "company_gstin": "29AARCA9330R1ZN",
        "billing_address_gstin": "",
        "place_of_supply": "96-Other Countries",
        "gst_category": "Overseas",
        "tax_category": "Overseas",
        "is_export_with_gst": 0,
        "taxes_and_charges": None,
    }
    fields.update(overrides)
    return FakeDoc("Sales Invoice", **fields)


def make_domestic_si(**overrides):
    """Inter-state domestic SI — Karnataka seller, Tamil Nadu buyer."""
    fields = {
        "company": _AETPL_INDIA,
        "customer": "C-AETPL-00001",
        "company_gstin": "29AARCA9330R1ZN",
        "billing_address_gstin": "33AAAAA0000A1Z5",
        "place_of_supply": "33-Tamil Nadu",
        "gst_category": "Registered Regular",
        "tax_category": "Out-State",
        "taxes_and_charges": None,
    }
    fields.update(overrides)
    return FakeDoc("Sales Invoice", **fields)


class TestIsNonDomesticSupply(unittest.TestCase):
    def test_overseas_gst_category(self):
        self.assertTrue(_is_non_domestic_supply(FakeDoc(gst_category="Overseas")))

    def test_sez_gst_categories(self):
        self.assertTrue(_is_non_domestic_supply(FakeDoc(gst_category="SEZ Unit")))
        self.assertTrue(_is_non_domestic_supply(FakeDoc(gst_category="SEZ Developer")))

    def test_overseas_tax_category(self):
        """gst_category not yet populated at before_validate — signal 2."""
        self.assertTrue(_is_non_domestic_supply(FakeDoc(tax_category="Overseas")))

    def test_export_place_of_supply(self):
        """Neither category populated — signal 3 still catches it."""
        self.assertTrue(
            _is_non_domestic_supply(FakeDoc(place_of_supply="96-Other Countries"))
        )

    def test_domestic_is_not_flagged(self):
        self.assertFalse(_is_non_domestic_supply(make_domestic_si()))

    def test_empty_doc_is_not_flagged(self):
        """No signals at all → domestic. Never guess an export."""
        self.assertFalse(_is_non_domestic_supply(FakeDoc()))

    def test_state_29_is_not_mistaken_for_96(self):
        """Guard against a substring/prefix slip on place_of_supply."""
        self.assertFalse(_is_non_domestic_supply(FakeDoc(place_of_supply="29-Karnataka")))


class TestExportBailsOut(unittest.TestCase):
    """Layer 0 — LTD-26-27-00798 regression."""

    def test_export_gets_no_domestic_template(self):
        doc = make_export_si()
        with patch("avientek.events.utils._resolve_aetpl_state_pair") as resolve:
            autofill_india_sales_taxes_template(doc)
        # Bailed before even resolving the state pair.
        resolve.assert_not_called()
        self.assertIsNone(doc.get("taxes_and_charges"))
        self.assertEqual(doc.taxes, [])

    def test_export_with_existing_igst_row_is_left_alone(self):
        """The reported symptom: an 18% IGST row must not be re-stamped
        or refilled on save. Removing it stays removed."""
        doc = make_export_si(taxes_and_charges=_AETPL_OUTSTATE_TEMPLATE)
        with patch("avientek.events.utils._apply_template_rows") as apply_rows:
            autofill_india_sales_taxes_template(doc)
        apply_rows.assert_not_called()
        self.assertEqual(doc.taxes, [])

    def test_export_with_user_picked_export_template_is_respected(self):
        doc = make_export_si(taxes_and_charges="Export GST - AETPL")
        with patch("avientek.events.utils._apply_template_rows") as apply_rows:
            autofill_india_sales_taxes_template(doc)
        apply_rows.assert_not_called()
        self.assertEqual(doc.taxes_and_charges, "Export GST - AETPL")

    def test_export_with_payment_of_igst_also_bails(self):
        """is_export_with_gst=1 DOES carry IGST — but the rate comes from
        the user's Export template, not from the domestic Out-state one."""
        doc = make_export_si(is_export_with_gst=1)
        with patch("avientek.events.utils._apply_template_rows") as apply_rows:
            autofill_india_sales_taxes_template(doc)
        apply_rows.assert_not_called()

    def test_export_on_quotation_and_sales_order_also_bail(self):
        for doctype in ("Quotation", "Sales Order"):
            doc = make_export_si()
            doc.doctype = doctype
            with patch("avientek.events.utils._apply_template_rows") as apply_rows:
                autofill_india_sales_taxes_template(doc)
            apply_rows.assert_not_called()


class TestDomesticStillWorks(unittest.TestCase):
    """Layers 1-3 must be untouched by the Layer 0 guard."""

    def test_interstate_domestic_gets_outstate_template(self):
        doc = make_domestic_si()
        with patch("avientek.events.utils.frappe") as fr, patch(
            "avientek.events.utils._apply_template_rows"
        ) as apply_rows:
            fr.db.exists.return_value = True
            autofill_india_sales_taxes_template(doc)
        self.assertEqual(doc.taxes_and_charges, _AETPL_OUTSTATE_TEMPLATE)
        apply_rows.assert_called_once_with(doc, _AETPL_OUTSTATE_TEMPLATE)

    def test_intrastate_domestic_gets_instate_template(self):
        doc = make_domestic_si(
            billing_address_gstin="29BBBBB0000B1Z5",
            place_of_supply="29-Karnataka",
            tax_category="In-State",
        )
        with patch("avientek.events.utils.frappe") as fr, patch(
            "avientek.events.utils._apply_template_rows"
        ) as apply_rows:
            fr.db.exists.return_value = True
            autofill_india_sales_taxes_template(doc)
        self.assertEqual(doc.taxes_and_charges, _AETPL_INSTATE_TEMPLATE)
        apply_rows.assert_called_once_with(doc, _AETPL_INSTATE_TEMPLATE)

    def test_wrong_direction_domestic_is_auto_corrected(self):
        """Layer 2 — In-state picked on an inter-state sale."""
        doc = make_domestic_si(taxes_and_charges=_AETPL_INSTATE_TEMPLATE)
        with patch("avientek.events.utils.frappe") as fr, patch(
            "avientek.events.utils._apply_template_rows"
        ) as apply_rows:
            fr.db.exists.return_value = True
            autofill_india_sales_taxes_template(doc)
        self.assertEqual(doc.taxes_and_charges, _AETPL_OUTSTATE_TEMPLATE)
        apply_rows.assert_called_once_with(doc, _AETPL_OUTSTATE_TEMPLATE)

    def test_non_aetpl_template_is_respected(self):
        """Layer 3 — unchanged."""
        doc = make_domestic_si(taxes_and_charges="Some Custom Template - AETPL")
        with patch("avientek.events.utils.frappe") as fr, patch(
            "avientek.events.utils._apply_template_rows"
        ) as apply_rows:
            fr.db.exists.return_value = True
            autofill_india_sales_taxes_template(doc)
        apply_rows.assert_not_called()
        self.assertEqual(doc.taxes_and_charges, "Some Custom Template - AETPL")

    def test_other_company_is_noop(self):
        doc = make_domestic_si(company="Avientek Trading WLL")
        with patch("avientek.events.utils._apply_template_rows") as apply_rows:
            autofill_india_sales_taxes_template(doc)
        apply_rows.assert_not_called()

    def test_other_doctype_is_noop(self):
        doc = make_domestic_si()
        doc.doctype = "Delivery Note"
        with patch("avientek.events.utils._apply_template_rows") as apply_rows:
            autofill_india_sales_taxes_template(doc)
        apply_rows.assert_not_called()


if __name__ == "__main__":
    unittest.main()
