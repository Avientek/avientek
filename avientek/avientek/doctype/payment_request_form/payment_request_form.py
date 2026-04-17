# Copyright (c) 2023, Craft and contributors
# For license information, please see license.txt

import frappe
import io
import os
import base64
import requests
from pypdf import PdfMerger
from bs4 import BeautifulSoup
from frappe.utils.pdf import get_pdf
from frappe.utils.file_manager import save_file
import json
from frappe.model.mapper import get_mapped_doc
from frappe.model.naming import make_autoname
from frappe.model.document import Document
from frappe import ValidationError, _, qb, scrub, throw
from frappe.query_builder.functions import Sum
from frappe.query_builder.utils import DocType
from pypika import Order
from frappe.utils import getdate, nowdate
from frappe.contacts.doctype.address.address import get_address_display
from pypika.terms import ExistsCriterion
from frappe.query_builder import AliasedQuery, Criterion, Table
from erpnext.controllers.accounts_controller import (
	AccountsController,
	get_supplier_block_status,
	validate_taxes_and_charges,
)

# class PaymentRequestForm(Document):
# 	def setUp(self):
# 		create_workflow()
class PaymentRequestForm(Document):
	pass
def create_workflow():

	if not frappe.db.exists("Workflow", "Payment Request Form"):
		workflow = frappe.new_doc("Workflow")
		workflow.workflow_name = "Payment Request Form"
		workflow.document_type = "Payment Request Form"
		workflow.workflow_state_field = "workflow_state"
		workflow.is_active = 1
		workflow.send_email_alert = 0
		workflow.append("states", dict(state="Pending", allow_edit="Accounts User"))
		workflow.append("states",dict(state="Approved", allow_edit="Accounts Manager"))
		workflow.append("states", dict(state="Rejected", allow_edit="Accounts Manager"))
		workflow.append("states", dict(state="Cancelled", allow_edit="Accounts Manager"))
		workflow.append(
			"transitions",
			dict(
				state="Pending",
				action="Approve",
				next_state="Approved",
				allowed="Accounts Manager",
				allow_self_approval=0,
				# condition=doc.approved_amount > 0
			),
		)
		workflow.append(
			"transitions",
			dict(
				state="Approved",
				action="Cancel",
				next_state="Cancelled",
				allowed="Accounts Manager",
				allow_self_approval=0,
				# condition=doc.approved_amount > 0
			),
		)
		workflow.append(
			"transitions",
			dict(
				state="Pending",
				action="Reject",
				next_state="Rejected",
				allowed="Accounts Manager",
				allow_self_approval=0,
				# condition=doc.approved_amount > 0
			),
		)
		workflow.append(
			"transitions",
			dict(
				state="Rejected", action="Review", next_state="Pending", allowed="Accounts User", allow_self_approval=1
			),
		)
		workflow.insert(ignore_permissions=True)
# def get_permission_query_conditions(user):
#     if "Accounts Manager" in frappe.get_roles(user):
#         return """(`tabPayment Request Form`.workflow_state = 'Pending Accounts Manager'
#                     OR `tabPayment Request Form`.modified_by = '{user}')""".format(user=user)

def _get_customer_credit_documents(args):
    """Fetch Credit Notes (return Sales Invoices) and credit Journal Entries for a customer."""
    from frappe.utils import flt

    if not args.get("party") or not args.get("company"):
        return []

    company_currency = frappe.get_cached_value("Company", args.get("company"), "default_currency")
    rows = []

    # 1. Credit Notes (Sales Invoice with is_return=1)
    credit_notes = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": args.get("party"),
            "company": args.get("company"),
            "is_return": 1,
            "docstatus": 1,
            "outstanding_amount": ["!=", 0],
        },
        fields=[
            "name", "posting_date", "due_date", "grand_total", "base_grand_total",
            "outstanding_amount", "currency", "conversion_rate", "return_against",
        ],
    )

    for cn in credit_notes:
        exchange_rate = flt(cn.conversion_rate) or 1
        os_company = abs(flt(cn.outstanding_amount))
        os_invoice = os_company / exchange_rate if exchange_rate else os_company

        rows.append({
            "voucher_type": "Credit Note",
            "voucher_no": cn.name,
            "bill_no": cn.name,
            "posting_date": cn.posting_date,
            "due_date": cn.due_date,
            "grand_total": abs(flt(cn.grand_total)),
            "base_grand_total": abs(flt(cn.base_grand_total)),
            "outstanding": os_invoice,
            "base_outstanding": os_company,
            "currency": cn.currency,
            "exchange_rate": exchange_rate,
            "is_return": 1,
            "return_against": cn.return_against or "",
            "document_reference": cn.return_against or "",
        })

    # 2. Journal Entries with credit for this customer
    je_accounts = frappe.get_all(
        "Journal Entry Account",
        filters={
            "party_type": "Customer",
            "party": args.get("party"),
            "credit_in_account_currency": [">", 0],
            "docstatus": 1,
        },
        fields=["parent", "credit_in_account_currency", "credit", "account_currency", "exchange_rate"],
    )

    # Group by parent JE and check if already fully allocated
    seen_je = set()
    for jea in je_accounts:
        if jea.parent in seen_je:
            continue
        seen_je.add(jea.parent)

        je = frappe.get_doc("Journal Entry", jea.parent)
        if je.company != args.get("company") or je.docstatus != 1:
            continue

        # Group party credit accounts by currency to avoid mixing currencies
        currency_groups = {}
        for acc in je.accounts:
            if acc.party_type == "Customer" and acc.party == args.get("party") and flt(acc.credit_in_account_currency) > 0:
                curr = acc.account_currency or company_currency
                if curr not in currency_groups:
                    currency_groups[curr] = {"credit": 0, "base_credit": 0, "exchange_rate": flt(acc.exchange_rate) or 1}
                currency_groups[curr]["credit"] += flt(acc.credit_in_account_currency)
                currency_groups[curr]["base_credit"] += flt(acc.credit)

        for curr, data in currency_groups.items():
            if data["credit"] <= 0:
                continue

            rows.append({
                "voucher_type": "Journal Entry",
                "voucher_no": je.name,
                "bill_no": je.name,
                "posting_date": je.posting_date,
                "due_date": je.posting_date,
                "grand_total": data["credit"],
                "base_grand_total": data["base_credit"],
                "outstanding": data["credit"],
                "base_outstanding": data["base_credit"],
                "currency": curr,
                "exchange_rate": data["exchange_rate"],
                "is_return": 0,
                "return_against": "",
                "document_reference": je.user_remark or "",
            })

    # 3. Payment Entries with unallocated amount for this customer
    payment_entries = frappe.get_all(
        "Payment Entry",
        filters={
            "party_type": "Customer",
            "party": args.get("party"),
            "company": args.get("company"),
            "docstatus": 1,
            "unallocated_amount": [">", 0],
        },
        fields=[
            "name", "posting_date", "paid_amount", "base_paid_amount",
            "unallocated_amount", "payment_type",
            "paid_from_account_currency", "paid_to_account_currency",
            "source_exchange_rate", "target_exchange_rate",
        ],
    )

    for pe in payment_entries:
        currency = pe.paid_from_account_currency if pe.payment_type == "Pay" else pe.paid_to_account_currency
        exchange_rate = flt(pe.source_exchange_rate if pe.payment_type == "Pay" else pe.target_exchange_rate) or 1
        os_invoice = flt(pe.unallocated_amount) / exchange_rate if exchange_rate else flt(pe.unallocated_amount)

        rows.append({
            "voucher_type": "Payment Entry",
            "voucher_no": pe.name,
            "bill_no": pe.name,
            "posting_date": pe.posting_date,
            "due_date": pe.posting_date,
            "grand_total": flt(pe.paid_amount),
            "base_grand_total": flt(pe.base_paid_amount),
            "outstanding": os_invoice,
            "base_outstanding": flt(pe.unallocated_amount),
            "currency": currency or company_currency,
            "exchange_rate": exchange_rate,
            "is_return": 0,
            "return_against": "",
            "document_reference": f"{pe.payment_type}: {pe.name}",
        })

    return rows


def _get_outstanding_employee_journal_entries(args):
    """Fetch outstanding Journal Entries with credit for an employee (company owes the employee).

    Issue 10: Filter out JEs that have been fully paid via Payment Ledger Entry
    or offset by a corresponding debit entry.
    """
    from frappe.utils import flt

    if not args.get("party") or not args.get("company"):
        return []

    company_currency = frappe.get_cached_value("Company", args.get("company"), "default_currency")
    rows = []

    je_accounts = frappe.get_all(
        "Journal Entry Account",
        filters={
            "party_type": "Employee",
            "party": args.get("party"),
            "credit_in_account_currency": [">", 0],
            "docstatus": 1,
        },
        fields=["parent", "credit_in_account_currency", "credit", "account_currency", "exchange_rate"],
    )

    seen_je = set()
    for jea in je_accounts:
        if jea.parent in seen_je:
            continue
        seen_je.add(jea.parent)

        je = frappe.get_doc("Journal Entry", jea.parent)
        if je.company != args.get("company") or je.docstatus != 1:
            continue

        # Issue 10: Skip if this JE is already referenced (paid) via Payment Ledger Entry
        # Check if there are DEBIT PLE entries against this JE that offset the credit
        try:
            ple_outstanding = frappe.db.sql(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM `tabPayment Ledger Entry`
                WHERE against_voucher_type = 'Journal Entry'
                AND against_voucher_no = %s
                AND party_type = 'Employee'
                AND party = %s
                AND delinked = 0
                """,
                (je.name, args.get("party")),
            )[0][0] or 0
        except Exception:
            ple_outstanding = None

        currency_groups = {}
        for acc in je.accounts:
            if acc.party_type == "Employee" and acc.party == args.get("party") and flt(acc.credit_in_account_currency) > 0:
                curr = acc.account_currency or company_currency
                if curr not in currency_groups:
                    currency_groups[curr] = {"credit": 0, "base_credit": 0, "exchange_rate": flt(acc.exchange_rate) or 1}
                currency_groups[curr]["credit"] += flt(acc.credit_in_account_currency)
                currency_groups[curr]["base_credit"] += flt(acc.credit)

        # If PLE shows fully paid/zero outstanding for this JE, skip it
        if ple_outstanding is not None and abs(ple_outstanding) < 0.01:
            # Only skip if we're sure PLE tracks this JE — i.e., it had entries originally
            ple_has_entries = frappe.db.exists(
                "Payment Ledger Entry",
                {"voucher_no": je.name, "party": args.get("party"), "delinked": 0},
            )
            if ple_has_entries:
                continue

        for curr, data in currency_groups.items():
            if data["credit"] <= 0:
                continue

            rows.append({
                "voucher_type": "Journal Entry",
                "voucher_no": je.name,
                "bill_no": je.name,
                "posting_date": je.posting_date,
                "due_date": je.posting_date,
                "grand_total": data["credit"],
                "base_grand_total": data["base_credit"],
                "outstanding": data["credit"],
                "base_outstanding": data["base_credit"],
                "currency": curr,
                "exchange_rate": data["exchange_rate"],
                "is_return": 0,
                "return_against": "",
                "document_reference": je.user_remark or "",
            })

    return rows


def _get_outstanding_employee_advances(args):
    """Fetch outstanding Employee Advances for an employee (advances that need to be paid to the employee)."""
    from frappe.utils import flt

    if not args.get("party") or not args.get("company"):
        return []

    company_currency = frappe.get_cached_value("Company", args.get("company"), "default_currency")

    # Get Employee Advances that are unpaid or partially paid
    advances = frappe.get_all(
        "Employee Advance",
        filters={
            "employee": args.get("party"),
            "company": args.get("company"),
            "docstatus": 1,
            "status": ["in", ["Unpaid", "Partly Paid and Claimed", "Partly Claimed and Returned"]],
        },
        fields=[
            "name", "posting_date", "advance_amount", "paid_amount",
            "claimed_amount", "return_amount", "currency", "exchange_rate",
            "purpose",
        ],
    )

    rows = []
    for ea in advances:
        # Outstanding = advance_amount - paid_amount
        outstanding = flt(ea.advance_amount) - flt(ea.paid_amount)
        if outstanding <= 0:
            continue

        # Get exchange rate, default to 1
        exchange_rate = flt(ea.exchange_rate) or 1
        currency = ea.currency or company_currency

        rows.append({
            "voucher_type": "Employee Advance",
            "voucher_no": ea.name,
            "bill_no": ea.name,
            "posting_date": ea.posting_date,
            "due_date": ea.posting_date,
            "grand_total": flt(ea.advance_amount),
            "base_grand_total": flt(ea.advance_amount) * exchange_rate,
            "outstanding": outstanding,
            "base_outstanding": outstanding * exchange_rate,
            "currency": currency,
            "exchange_rate": exchange_rate,
            "is_return": 0,
            "return_against": "",
            "document_reference": ea.purpose or "",
        })

    return rows


def _get_outstanding_expense_claims(args):
    """Fetch outstanding Expense Claims for an employee."""
    from frappe.utils import flt

    if not args.get("party") or not args.get("company"):
        return []

    company_currency = frappe.get_cached_value("Company", args.get("company"), "default_currency")

    claims = frappe.get_all(
        "Expense Claim",
        filters={
            "employee": args.get("party"),
            "company": args.get("company"),
            "docstatus": 1,
            "status": ["in", ["Unpaid", "Partly Paid"]],
        },
        fields=[
            "name", "posting_date", "total_sanctioned_amount",
            "total_amount_reimbursed", "cost_center",
        ],
    )

    rows = []
    for ec in claims:
        outstanding = flt(ec.total_sanctioned_amount) - flt(ec.total_amount_reimbursed)
        if outstanding <= 0:
            continue

        rows.append({
            "voucher_type": "Expense Claim",
            "voucher_no": ec.name,
            "bill_no": ec.name,
            "posting_date": ec.posting_date,
            "due_date": ec.posting_date,
            "grand_total": flt(ec.total_sanctioned_amount),
            "base_grand_total": flt(ec.total_sanctioned_amount),
            "outstanding": outstanding,
            "base_outstanding": outstanding,
            "currency": company_currency,
            "exchange_rate": 1,
            "is_return": 0,
            "return_against": "",
            "document_reference": "",
        })

    return rows


def _get_outstanding_purchase_orders(args):
    """Fetch outstanding Purchase Orders for a supplier (for advance payments).

    Purchase Orders don't create Payment Ledger Entries until invoiced,
    so we query the Purchase Order doctype directly.
    """
    from frappe.utils import flt

    if not args.get("party") or not args.get("company"):
        return []

    company_currency = frappe.get_cached_value("Company", args.get("company"), "default_currency")

    purchase_orders = frappe.get_all(
        "Purchase Order",
        filters={
            "supplier": args.get("party"),
            "company": args.get("company"),
            "docstatus": 1,
            "status": ["not in", ["Completed", "Cancelled", "Closed"]],
        },
        fields=[
            "name", "transaction_date", "grand_total", "base_grand_total",
            "advance_paid", "currency", "conversion_rate", "schedule_date",
        ],
    )

    rows = []
    for po in purchase_orders:
        exchange_rate = flt(po.conversion_rate) or 1
        currency = po.currency or company_currency

        # advance_paid is in company currency; outstanding = base_grand_total - advance_paid
        outstanding_base = flt(po.base_grand_total) - flt(po.advance_paid)
        if outstanding_base <= 0:
            continue

        # Convert outstanding to PO currency
        outstanding_fc = outstanding_base / exchange_rate if exchange_rate else outstanding_base

        rows.append({
            "voucher_type": "Purchase Order",
            "voucher_no": po.name,
            "bill_no": po.name,
            "posting_date": po.transaction_date,
            "due_date": po.schedule_date or po.transaction_date,
            "grand_total": flt(po.grand_total),
            "base_grand_total": flt(po.base_grand_total),
            "outstanding": outstanding_fc,
            "base_outstanding": outstanding_base,
            "currency": currency,
            "exchange_rate": exchange_rate,
            "is_return": 0,
            "return_against": "",
            "document_reference": "",
        })

    return rows


@frappe.whitelist()
def get_outstanding_reference_documents(args):

    if isinstance(args, str):
        args = json.loads(args)

    # Early return if required fields are missing
    if not args.get("party") or not args.get("company"):
        return []

    if args.get("party_type") == "Supplier":
        supplier_status = get_supplier_block_status(args["party"])
        if supplier_status and supplier_status.get("on_hold"):
            if supplier_status.get("hold_type") == "All":
                return []
            elif supplier_status.get("hold_type") == "Payments":
                if not supplier_status.get("release_date") or getdate(nowdate()) <= supplier_status.get("release_date"):
                    return []

    # Expense Claims don't use Payment Ledger Entry - handle separately
    if args.get("reference_doctype") == "Expense Claim":
        return _get_outstanding_expense_claims(args)

    # Employee Advances don't use Payment Ledger Entry - handle separately
    if args.get("reference_doctype") == "Employee Advance":
        return _get_outstanding_employee_advances(args)

    # Combined Employee Documents - fetch Expense Claims, Employee Advances, and Journal Entries
    if args.get("reference_doctype") == "Employee Documents":
        expense_claims = _get_outstanding_expense_claims(args)
        employee_advances = _get_outstanding_employee_advances(args)
        journal_entries = _get_outstanding_employee_journal_entries(args)
        return expense_claims + employee_advances + journal_entries

    # Customer: fetch Credit Notes and credit JVs only
    if args.get("party_type") == "Customer":
        return _get_customer_credit_documents(args)

    ple = DocType("Payment Ledger Entry")
    company_currency = frappe.get_cached_value("Company", args.get("company"), "default_currency")

    common_filter = [
        ple.party_type == args.get("party_type"),
        ple.party == args.get("party"),
        ple.company == args.get("company"),
    ]

    if args.get("reference_doctype"):
        common_filter.append(ple.voucher_type == args.get("reference_doctype"))


    query_voucher_amount = (
        frappe.qb.from_(ple)
        .select(
            ple.account,
            ple.voucher_type,
            ple.voucher_no,
            ple.party_type,
            ple.party,
            ple.posting_date,
            ple.due_date,
            ple.account_currency.as_("currency"),
            ple.amount.as_("invoice_amount"),
            ple.amount_in_account_currency.as_("outstanding_in_account_currency"),
            Sum(ple.amount).as_("amount"),
            Sum(ple.amount_in_account_currency).as_("amount_in_account_currency"),
        )
        .where(ple.delinked == 0)
        .where(Criterion.all(common_filter))
        .groupby(ple.voucher_type, ple.voucher_no, ple.party_type, ple.party)
    )

    query_voucher_outstanding = (
        frappe.qb.from_(ple)
        .select(
            ple.account,
            ple.against_voucher_type.as_("voucher_type"),
            ple.against_voucher_no.as_("voucher_no"),
            ple.party_type,
            ple.party,
            ple.posting_date,
            ple.due_date,
            ple.account_currency.as_("currency"),
            Sum(ple.amount).as_("amount"),
            Sum(ple.amount_in_account_currency).as_("amount_in_account_currency"),
        )
        .where(ple.delinked == 0)
        .where(Criterion.all(common_filter))
        .groupby(ple.against_voucher_type, ple.against_voucher_no, ple.party_type, ple.party)
    )

    vouchers = query_voucher_amount.as_("vouchers")
    outstanding = query_voucher_outstanding.as_("outstanding")

    cte_query = (
        frappe.qb.with_(query_voucher_amount, "vouchers")
        .with_(query_voucher_outstanding, "outstanding")
        .from_(vouchers)
        .left_join(outstanding)
        .on(
            (vouchers.account == outstanding.account)
            & (vouchers.voucher_type == outstanding.voucher_type)
            & (vouchers.voucher_no == outstanding.voucher_no)
            & (vouchers.party_type == outstanding.party_type)
            & (vouchers.party == outstanding.party)
        )
        .select(
            vouchers.account,
            vouchers.voucher_type,
            vouchers.voucher_no,
            vouchers.party_type,
            vouchers.party,
            vouchers.posting_date,
            vouchers.amount.as_("invoice_amount"),
            vouchers.amount_in_account_currency.as_("invoice_amount_in_account_currency"),
            outstanding.amount.as_("outstanding"),
            outstanding.amount_in_account_currency.as_("outstanding_in_account_currency"),
            (vouchers.amount - outstanding.amount).as_("paid_amount"),
            (vouchers.amount_in_account_currency - outstanding.amount_in_account_currency).as_("paid_amount_in_account_currency"),
            vouchers.due_date,
            vouchers.currency,
        )
        .having(frappe.qb.Field("outstanding_in_account_currency") > 0)
    )

    voucher_outstandings = cte_query.run(as_dict=True)

    # ▶ Enhance data with Purchase Invoice details if applicable
    filtered_rows = []

    for row in voucher_outstandings:
        voucher_type = row.get("voucher_type")
        voucher_no = row.get("voucher_no")

        try:
            # Get outstanding amount directly from database (bypasses all caching)
            invoice_outstanding = frappe.db.get_value(
                voucher_type, voucher_no, "outstanding_amount"
            )
            os_company = invoice_outstanding if invoice_outstanding is not None else (row.get("outstanding") or 0)

            # Skip fully paid invoices (outstanding = 0)
            if os_company == 0:
                continue

            # Now fetch the full document for other fields
            invoice = frappe.get_doc(voucher_type, voucher_no)
            meta = frappe.get_meta(voucher_type)

            if voucher_type == "Purchase Invoice":
                # Use bill_no if available, otherwise use voucher_no
                row["bill_no"] = invoice.get("bill_no") or voucher_no
            else:
                # For other voucher types, use voucher number as bill number
                row["bill_no"] = voucher_no

            row["posting_date"] = invoice.get("posting_date")
            row["grand_total"] = invoice.get("grand_total") or invoice.get("total")
            row["invoice_amount"] = invoice.get("total") or invoice.get("grand_total")
            row["currency"] = invoice.get("currency")
            row["exchange_rate"] = invoice.get("conversion_rate") or 1

            # outstanding_amount in ERPNext is in company currency;
            # convert back to invoice currency so the grid is consistent
            row["outstanding"] = os_company / row["exchange_rate"] if row["exchange_rate"] else os_company
            row["total_amount"] = row["invoice_amount"]

            # Company currency equivalents
            row["base_grand_total"] = (row["grand_total"] or 0) * row["exchange_rate"]
            row["base_outstanding"] = os_company

            if voucher_type == "Purchase Invoice":
                purchase_order = frappe.get_value(
                    "Purchase Invoice Item",
                    {"parent": voucher_no},
                    "purchase_order",
                    order_by="idx asc"
                )
                row["document_reference"] = purchase_order

            filtered_rows.append(row)

            # Fetch related Debit Notes / Return Purchase Invoices (only with outstanding)
            if voucher_type == "Purchase Invoice":
                debit_notes = frappe.get_all(
                    "Purchase Invoice",
                    filters={
                        "return_against": voucher_no,
                        "is_return": 1,
                        "docstatus": 1,
                        "outstanding_amount": ["!=", 0]  # Only fetch debit notes with outstanding
                    },
                    fields=["name"]
                )

                for dn in debit_notes:
                    try:
                        # Get outstanding directly from database (bypasses caching)
                        dn_os_company = frappe.db.get_value(
                            "Purchase Invoice", dn.name, "outstanding_amount"
                        ) or 0

                        # Skip if outstanding is 0 (fully settled)
                        if dn_os_company == 0:
                            continue

                        dn_doc = frappe.get_doc("Purchase Invoice", dn.name)

                        dn_row = {
                            "voucher_type": "Debit Note",
                            "voucher_no": dn.name,
                            "bill_no": dn_doc.get("bill_no") or dn.name,
                            "posting_date": dn_doc.get("posting_date"),
                            "due_date": dn_doc.get("due_date"),
                            "grand_total": dn_doc.get("grand_total") or 0,
                            "invoice_amount": dn_doc.get("total") or dn_doc.get("grand_total") or 0,
                            "currency": dn_doc.get("currency"),
                            "exchange_rate": dn_doc.get("conversion_rate") or 1,
                            "is_return": 1,
                            "return_against": voucher_no
                        }

                        # Outstanding for debit notes (usually negative)
                        dn_row["outstanding"] = dn_os_company / dn_row["exchange_rate"] if dn_row["exchange_rate"] else dn_os_company
                        dn_row["total_amount"] = dn_row["invoice_amount"]
                        dn_row["base_grand_total"] = (dn_row["grand_total"] or 0) * dn_row["exchange_rate"]
                        dn_row["base_outstanding"] = dn_os_company
                        dn_row["document_reference"] = f"Return: {voucher_no}"

                        filtered_rows.append(dn_row)
                    except Exception:
                        frappe.log_error(frappe.get_traceback(), f"Error processing debit note {dn.name}")

        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Error processing voucher {voucher_type} {voucher_no}")

    # Fetch standalone Debit Notes (returns without linked Purchase Invoice)
    if args.get("reference_doctype") == "Purchase Invoice":
        # Get all voucher_nos already added (to avoid duplicates)
        # Check ALL types, not just "Debit Note", since PLE may add returns as "Purchase Invoice"
        existing_debit_notes = set()
        for row in filtered_rows:
            existing_debit_notes.add(row.get("voucher_no"))

        # Fetch standalone debit notes for this supplier
        standalone_debit_notes = frappe.get_all(
            "Purchase Invoice",
            filters={
                "supplier": args.get("party"),
                "company": args.get("company"),
                "is_return": 1,
                "docstatus": 1,
                "return_against": ["in", ["", None]],  # No linked invoice
                "outstanding_amount": ["!=", 0]
            },
            fields=["name"]
        )

        for dn in standalone_debit_notes:
            if dn.name in existing_debit_notes:
                continue  # Skip if already added

            try:
                # Get outstanding directly from database (bypasses caching)
                dn_os_company = frappe.db.get_value(
                    "Purchase Invoice", dn.name, "outstanding_amount"
                ) or 0

                # Skip if outstanding is 0 (fully settled)
                if dn_os_company == 0:
                    continue

                dn_doc = frappe.get_doc("Purchase Invoice", dn.name)

                dn_row = {
                    "voucher_type": "Debit Note",
                    "voucher_no": dn.name,
                    "bill_no": dn_doc.get("bill_no") or dn.name,
                    "posting_date": dn_doc.get("posting_date"),
                    "due_date": dn_doc.get("due_date"),
                    "grand_total": dn_doc.get("grand_total") or 0,
                    "invoice_amount": dn_doc.get("total") or dn_doc.get("grand_total") or 0,
                    "currency": dn_doc.get("currency"),
                    "exchange_rate": dn_doc.get("conversion_rate") or 1,
                    "is_return": 1,
                    "return_against": ""
                }

                # Outstanding for debit notes (usually negative)
                dn_row["outstanding"] = dn_os_company / dn_row["exchange_rate"] if dn_row["exchange_rate"] else dn_os_company
                dn_row["total_amount"] = dn_row["invoice_amount"]
                dn_row["base_grand_total"] = (dn_row["grand_total"] or 0) * dn_row["exchange_rate"]
                dn_row["base_outstanding"] = dn_os_company
                dn_row["document_reference"] = "Standalone Return"

                filtered_rows.append(dn_row)
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"Error processing standalone debit note {dn.name}")

    # Also include open Purchase Orders when fetching Purchase Invoices
    if args.get("reference_doctype") == "Purchase Invoice":
        po_rows = _get_outstanding_purchase_orders(args)
        filtered_rows.extend(po_rows)

    # Deduplicate by (voucher_type, voucher_no) — Issue 3 fix
    # Keep only the first occurrence of each voucher to prevent duplicates
    seen = set()
    deduped = []
    for row in filtered_rows:
        key = (row.get("voucher_type"), row.get("voucher_no"))
        if key in seen:
            continue
        seen.add(key)
        # Final filter: only include rows with positive outstanding
        # (except debit notes which have negative outstanding)
        os_amt = row.get("outstanding") or row.get("outstanding_in_account_currency") or 0
        if os_amt == 0 and not row.get("is_return"):
            continue
        deduped.append(row)

    return deduped


def get_formatted_supplier_address(address_name):
    """
    Given an address name (e.g., "SupplierName-Shipping"),
    fetch the Address document and return its formatted display text.
    """
    if not address_name:
        return ""

    try:
        # Fetch the Address document
        address_doc = frappe.get_doc("Address", address_name)

        # Get the formatted address display
        return get_address_display(address_doc.as_dict())

    except frappe.DoesNotExistError:
        return f"Address '{address_name}' not found."

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in get_formatted_supplier_address")
        return f"Error: {str(e)}"

@frappe.whitelist()
def get_supplier_address_display(address_name):
    return get_formatted_supplier_address(address_name)


@frappe.whitelist()
def get_supplier_bank_details(supplier_name, party_type="Supplier"):
    if not supplier_name:
        return {}

    # Prefer the party's default bank account; fall back to any enabled one.
    # Finance reported the wrong account flowing in when a supplier had more
    # than one; is_default=1 fixes that.
    bank_account = frappe.get_all(
        "Bank Account",
        filters={"party_type": party_type, "party": supplier_name, "is_default": 1, "disabled": 0},
        fields=["name", "bank", "bank_account_no", "iban", "branch_code"],
        limit=1,
    ) or frappe.get_all(
        "Bank Account",
        filters={"party_type": party_type, "party": supplier_name, "disabled": 0},
        fields=["name", "bank", "bank_account_no", "iban", "branch_code"],
        limit=1,
    )

    if not bank_account:
        return {}

    bank_data = bank_account[0]
    swift_code = ""
    if bank_data.get("bank"):
        swift_code = frappe.db.get_value("Bank", bank_data.bank, "swift_number") or ""

    return {
        "bank_account_no": bank_data.get("bank_account_no") or "",
        "iban": bank_data.get("iban") or "",
        "bank": bank_data.get("bank") or "",
        "branch_code": bank_data.get("branch_code") or "",
        "swift_code": swift_code,
        "supplier_bank_account": bank_data.get("name") or "",
    }

@frappe.whitelist()
def fetch_party_name(party_type, party):
    if not party_type or not party:
        return ""

    doc = frappe.get_doc(party_type, party)
    return doc.get("customer_name") or doc.get("supplier_name") or doc.get("employee_name") or doc.get("employee") or doc.name

@frappe.whitelist()
def create_payment_entry(source_name, target_doc=None, args=None):
    # def set_single_reference(source, target):
    #     target.append("references", {
    #         "reference_doctype": "Payment Request Form",
    #         "reference_name": source.name
    #         # "total_amount": source.payment_amount,
    #         # "outstanding_amount": source.outstanding_amount,
    #     })

    target_doc = get_mapped_doc(
        "Payment Request Form",
        source_name,
        {
            "Payment Request Form": {
                "doctype": "Payment Entry",
                "field_map": {
                    "payment_type": "payment_type",
                    "payment_mode": "mode_of_payment",
                    "supplier_bank_account": "party_bank_account",
                    "supplier_balance": "party_balance",
                    "account": "paid_from",
                    "issued_bank": "bank_account",
                    "total_payment_amount": "paid_amount",
                    "receiving_account": "paid_to",
                    "receiving_currency": "paid_to_account_currency",
                    "issued_currency": "paid_from_account_currency",
                    "name": "payment_request_form",
                    "total_received_amount": "received_amount"
                },
            }
        },
        target_doc,
        # postprocess=set_single_reference
    )

    return target_doc 


@frappe.whitelist()
def create_journal_entry(source_name, target_doc=None, args=None):
    target_doc = get_mapped_doc(
        "Payment Request Form",
        source_name,
        {
            "Payment Request Form": {
                "doctype": "Journal Entry",
                "field_map": {
                    "company": "company"
                },
            }
        },
        target_doc,
        # postprocess=set_single_reference
    )

    return target_doc


@frappe.whitelist()
def make_payment_order(source_name, target_doc=None):
    source = frappe.get_doc("Payment Request Form", source_name)

    def set_missing_values(source, target):
        target.payment_order_type = "Payment Request"
        target.company = source.company
        target.company_bank_account = source.issued_bank

        for row in source.payment_references:
            target.append("references", {
                "reference_doctype": row.reference_doctype,
                "reference_name": row.reference_name,
                "amount": row.payment_amount,
                "supplier": source.party,
                "mode_of_payment": source.payment_mode,
                "bank_account": source.supplier_bank_account,
                "account": source.account,
            })

    target_doc = get_mapped_doc(
        "Payment Request Form",
        source_name,
        {
            "Payment Request Form": {
                "doctype": "Payment Order",
                "validation": {"docstatus": ["=", 1]},
                "field_map": {
                    "company": "company",
                },
            },
        },
        target_doc,
        set_missing_values,
    )

    return target_doc


@frappe.whitelist()
def download_payment_pdf(docname):
    """Streams the combined PDF directly to the browser."""

    if not frappe.has_permission("Payment Request Form", "read", doc=docname):
        frappe.throw("Not permitted")

    doc = frappe.get_doc("Payment Request Form", docname)
    base_url = frappe.utils.get_url()
    session_cookie = frappe.local.request.cookies.get("sid")
    headers = {"Cookie": f"sid={session_cookie}"}

    merger = PdfMerger()

    # Merge Payment Request Form
    try:
        # Use "Payment Voucher Fast" as the primary format — it's the complete
        # voucher (bank details, IBAN, supplier address, dynamic columns, Doc
        # Reference label, TR/LC application on page 2). Falls back to the
        # older formats only if Fast is missing.
        print_format_name = "Payment Voucher Fast"
        if not frappe.db.exists("Print Format", print_format_name):
            print_format_name = "Payment Voucher Professional"
        if not frappe.db.exists("Print Format", print_format_name):
            print_format_name = "PAYMENT VOUCHER"

        print_format_pdf = frappe.get_print(
            "Payment Request Form",
            docname,
            print_format=print_format_name,
            as_pdf=True
        )
        merger.append(io.BytesIO(print_format_pdf))
    except Exception as e:
        frappe.log_error(f"Error merging print format PDF: {e}")

    # Loop through references
    for row in doc.payment_references:
        supplier_bill_no = row.reference_name

        # Get Purchase Invoice name from Supplier Bill No
        purchase_invoice_name = frappe.db.get_value(
            "Purchase Invoice",
            {"bill_no": supplier_bill_no},
            "name"
        )

        if not purchase_invoice_name:
            frappe.log_error(f"No Purchase Invoice found for Bill No: {supplier_bill_no}")
            continue

        # Purchase Invoice Attachment
        try:
            attachment = frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": "Purchase Invoice",
                    "attached_to_name": purchase_invoice_name
                },
                fields=["file_url"],
                order_by="creation asc",
                limit=1
            )
            if attachment:
                file_url = attachment[0]["file_url"]
                res = requests.get(
                    file_url if file_url.startswith("http") else base_url + file_url,
                    headers=headers, verify=False
                )
                if res.status_code == 200 and 'application/pdf' in res.headers.get('Content-Type', ''):
                    merger.append(io.BytesIO(res.content))
        except Exception as e:
            frappe.log_error(f"Error fetching Purchase Invoice attachment for {purchase_invoice_name}: {e}")

        # Purchase Order & Quotation PDFs
        try:
            purchase_order = frappe.get_value(
                "Purchase Invoice Item",
                {"parent": purchase_invoice_name},
                fieldname="purchase_order",
                order_by="idx asc",
            )
            if purchase_order:
                po_pdf = get_pdf(
                    frappe.get_print("Purchase Order", purchase_order, print_format="Avientek PO")
                )
                merger.append(io.BytesIO(po_pdf))

                sales_order = frappe.db.get_value(
                    "Purchase Order Item", {"parent": purchase_order}, "sales_order"
                )
                quotation = frappe.db.get_value(
                    "Sales Order Item", {"parent": sales_order}, "prevdoc_docname"
                ) if sales_order else None

                if quotation:
                    quotation_pdf = get_pdf(
                        frappe.get_print("Quotation", quotation, print_format="Quotation New")
                    )
                    merger.append(io.BytesIO(quotation_pdf))
        except Exception as e:
            frappe.log_error(f"Error fetching Quotation PDFs for {purchase_invoice_name}: {e}")

    # Bank Letter (Supplier only, after reference docs)
    if doc.bank_letter:
        try:
            file_url = doc.bank_letter
            if file_url.lower().endswith('.pdf'):
                if not file_url.startswith("http"):
                    file_url = base_url + file_url
                res = requests.get(file_url, headers=headers, verify=False)
                if res.status_code == 200 and 'application/pdf' in res.headers.get('Content-Type', ''):
                    merger.append(io.BytesIO(res.content))
        except Exception as e:
            frappe.log_error(f"Error merging bank letter: {e}")

    # Additional Documents (always last in the combined PDF)
    for addl_doc in (doc.additional_documents or []):
        if not addl_doc.attachment:
            continue
        try:
            file_url = addl_doc.attachment
            if file_url.lower().endswith('.pdf'):
                if not file_url.startswith("http"):
                    file_url = base_url + file_url
                res = requests.get(file_url, headers=headers, verify=False)
                if res.status_code == 200 and 'application/pdf' in res.headers.get('Content-Type', ''):
                    merger.append(io.BytesIO(res.content))
        except Exception as e:
            frappe.log_error(f"Error merging additional document {addl_doc.label}: {e}")

    # Output merged PDF
    output = io.BytesIO()
    merger.write(output)
    merger.close()
    output.seek(0)

    frappe.local.response.filename = f"{docname}_combined.pdf"
    frappe.local.response.filecontent = output.read()
    frappe.local.response.type = "download"


@frappe.whitelist()
def get_voucher_print_data(docname):
    """
    Single consolidated method for the Payment Voucher print format.
    Fetches all data needed in one call to avoid multiple round-trips from Jinja.
    """
    doc = frappe.get_doc("Payment Request Form", docname)

    company_currency = frappe.db.get_value("Company", doc.company, "default_currency") or "AED"

    # Supplier/party bank details
    supplier_bank = frappe.db.get_value(
        "Bank Account",
        {"party_type": doc.party_type, "party": doc.party, "is_default": 1},
        ["name", "bank", "bank_account_no", "iban", "branch_code"],
        as_dict=True
    ) or {}
    supplier_swift = ""
    if supplier_bank and supplier_bank.get("bank"):
        supplier_swift = frappe.db.get_value("Bank", supplier_bank.bank, "swift_number") or ""

    # Issued bank details (single query instead of two)
    issued_bank_details = frappe.db.get_value(
        "Bank Account", doc.issued_bank,
        ["bank", "bank_account_no", "iban", "account_currency"],
        as_dict=True
    ) or {}
    issued_bank_currency = issued_bank_details.get("account_currency") or company_currency

    # Payment history
    payment_history = get_supplier_payment_history(doc.party, doc.company, limit=10)

    # Previous payment attachment images
    first_row = doc.payment_references[0] if doc.payment_references else None
    prev_payment_attachment = first_row.previous_payment_details if first_row else None
    prev_payment_images = []
    if prev_payment_attachment:
        prev_payment_images = get_attachment_as_images(prev_payment_attachment, max_pages=3) or []

    # Pre-compute all per-row attachment data
    ref_label_map = {
        "Purchase Invoice": "Supplier Invoice", "Debit Note": "Debit Note",
        "Credit Note": "Credit Note", "Sales Invoice": "Sales Invoice",
        "Expense Claim": "Expense Claim", "Payment Entry": "Payment Entry",
        "Journal Entry": "Journal Entry", "Purchase Order": "Purchase Order"
    }
    row_attachments = []
    for row in doc.payment_references:
        row_data = {"ref_images": [], "po_images": [], "costing_images": [], "ref_label": "", "ref_name": "", "linked_po": ""}
        if row.reference_doctype and row.reference_doctype != "Manual" and row.reference_name:
            row_data["ref_label"] = ref_label_map.get(row.reference_doctype, row.reference_doctype)
            row_data["ref_name"] = row.reference_name
            row_data["ref_images"] = get_reference_attachment_images(row.reference_doctype, row.reference_name, max_pages=3) or []

            # Linked PO (supplier only)
            if doc.party_type == "Supplier" and row.reference_doctype in ("Purchase Invoice", "Debit Note"):
                linked_po = get_linked_po_for_invoice(row.reference_name)
                if linked_po:
                    row_data["linked_po"] = linked_po
                    row_data["po_images"] = get_print_format_as_images("Purchase Order", linked_po, print_format="Purchase Order - India", max_pages=3) or []

                # Costing sheet
                if row.costing_sheet_attachment:
                    row_data["costing_images"] = get_attachment_as_images(row.costing_sheet_attachment, max_pages=3) or []

        row_attachments.append(row_data)

    return {
        "company_currency": company_currency,
        "supplier_bank": supplier_bank,
        "supplier_swift": supplier_swift,
        "issued_bank_details": issued_bank_details,
        "issued_bank_currency": issued_bank_currency,
        "payment_history": payment_history,
        "prev_payment_images": prev_payment_images,
        "row_attachments": row_attachments,
    }


@frappe.whitelist()
def get_supplier_payment_history(supplier, company=None, limit=50):
    """
    Fetch payment history for a supplier from Payment Entry and Journal Entry.
    Returns a list of payment records with bank details, voucher info, and amounts.
    """
    if not supplier:
        return []

    # Ensure limit is an integer
    limit = int(limit) if limit else 50

    payment_history = []

    # 1. Fetch from Payment Entry
    pe_filters = {
        "party_type": "Supplier",
        "party": supplier,
        "payment_type": "Pay",
        "docstatus": 1
    }
    if company:
        pe_filters["company"] = company

    payment_entries = frappe.get_all(
        "Payment Entry",
        filters=pe_filters,
        fields=[
            "name", "posting_date", "party", "party_name",
            "paid_amount", "paid_from", "paid_from_account_currency",
            "bank_account", "party_bank_account", "reference_no",
            "mode_of_payment", "company"
        ],
        order_by="posting_date desc",
        limit_page_length=limit
    )

    # Batch-fetch all bank account details to avoid N+1 queries
    all_bank_accounts = set()
    for pe in payment_entries:
        if pe.bank_account:
            all_bank_accounts.add(pe.bank_account)
        if pe.party_bank_account:
            all_bank_accounts.add(pe.party_bank_account)

    bank_account_map = {}
    if all_bank_accounts:
        bank_rows = frappe.get_all(
            "Bank Account",
            filters={"name": ["in", list(all_bank_accounts)]},
            fields=["name", "bank", "bank_account_no", "iban"]
        )
        bank_account_map = {r.name: r for r in bank_rows}

    for pe in payment_entries:
        bank_name = ""
        beneficiary_account = ""
        debit_account_no = ""

        if pe.bank_account and pe.bank_account in bank_account_map:
            bd = bank_account_map[pe.bank_account]
            bank_name = bd.get("bank") or ""
            debit_account_no = bd.get("bank_account_no") or ""

        if pe.party_bank_account and pe.party_bank_account in bank_account_map:
            pbd = bank_account_map[pe.party_bank_account]
            beneficiary_account = pbd.get("iban") or pbd.get("bank_account_no") or ""

        payment_type_code = "TR"
        if pe.mode_of_payment:
            mop = pe.mode_of_payment.upper()
            if "TT" in mop or "TELEGRAPHIC" in mop:
                payment_type_code = "TT"

        payment_history.append({
            "sl_no": 0,
            "bank": bank_name,
            "type": payment_type_code,
            "voucher_no": pe.name,
            "date": pe.posting_date,
            "beneficiary": pe.party_name or pe.party,
            "beneficiary_account": beneficiary_account,
            "debit_account": debit_account_no,
            "currency": pe.paid_from_account_currency or "AED",
            "amount": pe.paid_amount or 0,
            "source": "Payment Entry"
        })

    # 2. Fetch from Journal Entry (Bank Entry type with supplier)
    je_query = """
        SELECT
            je.name, je.posting_date, je.cheque_no, je.mode_of_payment,
            jea.party, jea.party_type, jea.debit_in_account_currency,
            jea.account, jea.account_currency, jea.bank_account
        FROM `tabJournal Entry` je
        INNER JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
        WHERE je.docstatus = 1
            AND jea.party_type = 'Supplier'
            AND jea.party = %(supplier)s
            AND jea.debit_in_account_currency > 0
    """
    if company:
        je_query += " AND je.company = %(company)s"
    je_query += f" ORDER BY je.posting_date DESC LIMIT {limit}"

    journal_entries = frappe.db.sql(
        je_query,
        {"supplier": supplier, "company": company},
        as_dict=True
    )

    # Batch-fetch JE bank accounts
    je_bank_accounts = set()
    for je in journal_entries:
        if je.bank_account:
            je_bank_accounts.add(je.bank_account)

    je_bank_map = {}
    if je_bank_accounts:
        je_bank_rows = frappe.get_all(
            "Bank Account",
            filters={"name": ["in", list(je_bank_accounts)]},
            fields=["name", "bank", "bank_account_no"]
        )
        je_bank_map = {r.name: r for r in je_bank_rows}

    # Fetch supplier default bank & name once (not per row)
    supplier_bank = frappe.db.get_value(
        "Bank Account",
        {"party_type": "Supplier", "party": supplier, "is_default": 1},
        ["bank_account_no", "iban"],
        as_dict=True
    ) or {}
    beneficiary_account_default = supplier_bank.get("iban") or supplier_bank.get("bank_account_no") or ""
    supplier_name = frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier

    for je in journal_entries:
        bank_name = ""
        debit_account_no = ""

        if je.bank_account and je.bank_account in je_bank_map:
            bd = je_bank_map[je.bank_account]
            bank_name = bd.get("bank") or ""
            debit_account_no = bd.get("bank_account_no") or ""

        payment_type_code = "TR"
        if je.mode_of_payment:
            mop = je.mode_of_payment.upper()
            if "TT" in mop or "TELEGRAPHIC" in mop:
                payment_type_code = "TT"

        payment_history.append({
            "sl_no": 0,
            "bank": bank_name,
            "type": payment_type_code,
            "voucher_no": je.cheque_no or je.name,
            "date": je.posting_date,
            "beneficiary": supplier_name,
            "beneficiary_account": beneficiary_account_default,
            "debit_account": debit_account_no,
            "currency": je.account_currency or "AED",
            "amount": je.debit_in_account_currency or 0,
            "source": "Journal Entry"
        })

    # Sort by date descending and assign serial numbers
    payment_history.sort(key=lambda x: x["date"] or "", reverse=True)
    for idx, row in enumerate(payment_history, 1):
        row["sl_no"] = idx

    return payment_history


# ──────────────────────────── FAST PRINT CONTEXT ────────────────────────────
@frappe.whitelist()
def get_payment_voucher_context(docname):
    """
    Single batch call to pre-fetch ALL data needed by the Payment Voucher print format.
    Replaces multiple frappe.db.get_value() calls in the Jinja template.
    Returns a flat dict that the template can use directly.
    """
    from frappe.utils import flt, fmt_money, formatdate

    doc = frappe.get_doc("Payment Request Form", docname)
    company_currency = frappe.db.get_value("Company", doc.company, "default_currency") or "AED"

    # Issued bank details
    issued_bank_details = {}
    if doc.issued_bank:
        issued_bank_details = frappe.db.get_value(
            "Bank Account", doc.issued_bank,
            ["bank", "bank_account_no", "iban"], as_dict=True
        ) or {}

    # Receiving bank details (internal transfer only)
    receiving_bank_details = {}
    if doc.payment_type == "Internal Transfer" and doc.receiving_bank:
        receiving_bank_details = frappe.db.get_value(
            "Bank Account", doc.receiving_bank,
            ["bank", "bank_account_no", "iban"], as_dict=True
        ) or {}

    # Supplier/party bank details — Issue 13: show for Supplier, Employee, Customer
    supplier_bank = {}
    supplier_swift = ""
    if doc.payment_type != "Internal Transfer" and doc.party and doc.party_type:
        # 1. Prefer the bank account explicitly selected on the PRF
        if doc.get("supplier_bank_account"):
            supplier_bank = frappe.db.get_value(
                "Bank Account",
                doc.supplier_bank_account,
                ["name", "bank", "bank_account_no", "iban", "branch_code"],
                as_dict=True,
            ) or {}
        # 2. Default bank account for this party
        if not supplier_bank:
            supplier_bank = frappe.db.get_value(
                "Bank Account",
                {"party_type": doc.party_type, "party": doc.party, "is_default": 1},
                ["name", "bank", "bank_account_no", "iban", "branch_code"],
                as_dict=True,
            ) or {}
        # 3. Any bank account for this party (fallback for Employees without default)
        if not supplier_bank:
            supplier_bank = frappe.db.get_value(
                "Bank Account",
                {"party_type": doc.party_type, "party": doc.party},
                ["name", "bank", "bank_account_no", "iban", "branch_code"],
                as_dict=True,
            ) or {}
        if supplier_bank and supplier_bank.get("bank"):
            supplier_swift = frappe.db.get_value("Bank", supplier_bank["bank"], "swift_number") or ""

    # Pre-compute currency totals and base total from payment references
    currency_totals = {}
    total_base = 0
    rows_data = []
    for row in (doc.payment_references or []):
        amount_fc = flt(row.outstanding_amount or row.grand_total or 0)
        amount_base = flt(row.base_outstanding_amount or row.base_grand_total or 0)
        curr = row.currency or company_currency

        if curr not in currency_totals:
            currency_totals[curr] = 0
        currency_totals[curr] += amount_fc
        total_base += amount_base

        rows_data.append({
            "idx": row.idx,
            "reference_doctype": row.reference_doctype or "",
            "reference_name": row.reference_name or "",
            "invoice_date": formatdate(row.invoice_date, "dd-MM-yy") if row.invoice_date else "",
            "currency": curr,
            "amount_fc": fmt_money(amount_fc, currency=curr),
            "amount_base": fmt_money(amount_base, currency=company_currency),
            "document_reference": row.document_reference or row.remarks or "",
        })

    # Format currency totals
    formatted_currency_totals = []
    for curr, amount in currency_totals.items():
        formatted_currency_totals.append(fmt_money(amount, currency=curr))

    # TR/LC total
    tr_total = sum(
        flt(row.outstanding_amount or row.grand_total or 0)
        for row in (doc.payment_references or [])
    )

    # Pre-fetch ALL attachment images in one batch (avoids per-row frappe.call in Jinja)
    ref_label_map = {
        "Purchase Invoice": "Supplier Invoice", "Debit Note": "Debit Note",
        "Credit Note": "Credit Note", "Sales Invoice": "Sales Invoice",
        "Expense Claim": "Expense Claim", "Payment Entry": "Payment Entry",
        "Journal Entry": "Journal Entry", "Purchase Order": "Purchase Order"
    }
    row_attachments = []
    for row in (doc.payment_references or []):
        row_data = {"ref_images": [], "po_images": [], "costing_images": [], "ref_label": "", "ref_name": "", "linked_po": ""}
        if row.reference_doctype and row.reference_doctype != "Manual" and row.reference_name:
            row_data["ref_label"] = ref_label_map.get(row.reference_doctype, row.reference_doctype)
            row_data["ref_name"] = row.reference_name
            row_data["ref_images"] = get_reference_attachment_images(row.reference_doctype, row.reference_name, max_pages=3) or []

            # Linked PO (supplier only)
            if doc.party_type == "Supplier" and row.reference_doctype in ("Purchase Invoice", "Debit Note"):
                linked_po = get_linked_po_for_invoice(row.reference_name)
                if linked_po:
                    row_data["linked_po"] = linked_po
                    row_data["po_images"] = get_print_format_as_images("Purchase Order", linked_po, print_format="Purchase Order - India", max_pages=3) or []

                # Costing sheet
                if row.costing_sheet_attachment:
                    row_data["costing_images"] = get_attachment_as_images(row.costing_sheet_attachment, max_pages=3) or []

        row_attachments.append(row_data)

    return {
        "company_currency": company_currency,
        "issued_bank_details": issued_bank_details,
        "receiving_bank_details": receiving_bank_details,
        "supplier_bank": supplier_bank,
        "supplier_swift": supplier_swift,
        "issued_bank_currency": doc.issued_currency or company_currency,
        "receiving_bank_currency": doc.receiving_currency or company_currency,
        "party_name": doc.party_name or doc.party or "",
        "party_label": doc.party_type or "Party",
        # Address fallback — doc.address_display can be empty if the user
        # picked a Supplier Address but the fetch didn't run. Regenerate from
        # the linked Address record so the print always shows the address.
        "party_address": (
            doc.address_display
            or (get_formatted_supplier_address(doc.supplier_address) if doc.get("supplier_address") else "")
            or ""
        ),
        "rows_data": rows_data,
        "formatted_currency_totals": formatted_currency_totals,
        "total_base_formatted": fmt_money(total_base, currency=company_currency),
        "tr_total_formatted": "{:,.2f}".format(tr_total),
        "tr_currency": doc.currency or company_currency,
        "posting_date_fmt": formatdate(doc.posting_date, "d-M-yyyy") if doc.posting_date else "",
        "cheque_date_fmt": formatdate(doc.cheque_date, "d-M-yyyy") if doc.cheque_date else "",
        "issued_amount_fmt": fmt_money(flt(doc.issued_amount or 0), currency=doc.issued_currency or company_currency),
        "receiving_amount_fmt": fmt_money(flt(doc.receiving_amount or 0), currency=doc.receiving_currency or company_currency),
        "row_attachments": row_attachments,
    }


# ──────────────────────────── OPTIMIZED PDF CONVERSION HELPERS ────────────────────────────
import hashlib

def _get_cache_key(prefix, *args):
    """Generate a unique cache key from arguments."""
    key_data = "|".join(str(a) for a in args)
    return f"pdf_img_{prefix}_{hashlib.md5(key_data.encode()).hexdigest()[:16]}"


def _convert_pdf_to_images_optimized(pdf_source, max_pages=2, zoom=1.0, jpeg_quality=60, is_bytes=False):
    """
    Optimized PDF to image conversion with lower resolution and quality for faster loading.

    Args:
        pdf_source: File path (string) or PDF bytes (if is_bytes=True)
        max_pages: Maximum pages to convert (default 2 for speed)
        zoom: Zoom factor (1.0 = 72 DPI, lower = faster)
        jpeg_quality: JPEG quality 0-100 (lower = smaller file, faster)
        is_bytes: Whether pdf_source is bytes (True) or file path (False)

    Returns:
        List of base64 image data URIs
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []

    try:
        if is_bytes:
            pdf_document = fitz.open(stream=pdf_source, filetype="pdf")
        else:
            if not os.path.exists(pdf_source):
                return []
            pdf_document = fitz.open(pdf_source)

        images = []
        num_pages = min(pdf_document.page_count, max_pages)

        for page_num in range(num_pages):
            page = pdf_document.load_page(page_num)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            # Use JPEG with specified quality for smaller file size
            img_bytes = pix.tobytes(output="jpeg", jpg_quality=jpeg_quality)
            img_base64 = base64.b64encode(img_bytes).decode("utf-8")
            images.append(f"data:image/jpeg;base64,{img_base64}")

        pdf_document.close()
        return images
    except Exception as e:
        frappe.log_error(f"PDF conversion error: {str(e)}", "PDF to Image")
        return []


def _get_file_path_from_url(file_url):
    """Convert a file URL to absolute file path."""
    if not file_url:
        return None
    if file_url.startswith("/private/"):
        return frappe.get_site_path() + file_url
    elif file_url.startswith("/files/"):
        return frappe.get_site_path("public") + file_url
    return None


@frappe.whitelist()
def clear_pdf_cache(doctype=None, docname=None):
    """
    Clear PDF image cache for a specific document or all caches.
    Call this when attachments are updated.

    Args:
        doctype: Optional - clear cache for specific doctype
        docname: Optional - clear cache for specific document

    Returns:
        dict with status message
    """
    try:
        if doctype and docname:
            # Clear specific document caches
            for max_pages in [2, 5, 10]:
                cache_key = _get_cache_key("pdf_attach", doctype, docname, max_pages)
                frappe.cache().delete_value(cache_key)
                cache_key = _get_cache_key("ref_attach", doctype, docname, max_pages)
                frappe.cache().delete_value(cache_key)
            return {"status": "success", "message": f"Cleared cache for {doctype} {docname}"}
        else:
            # Clear all PDF caches (pattern-based clearing not available, so just return info)
            return {"status": "info", "message": "Caches will expire automatically in 5 minutes"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def get_pdf_as_images(doctype, docname, max_pages=2):
    """
    Get PDF attachments for a document and convert them to base64 images.
    OPTIMIZED: Uses caching, lower resolution (1.0x), JPEG quality 60.

    Args:
        doctype: The doctype to fetch attachments from
        docname: The document name
        max_pages: Maximum number of pages to convert per PDF (default: 2)

    Returns:
        List of dicts with 'file_name' and 'images' (list of base64 image strings)
    """
    if not doctype or not docname:
        return []

    max_pages = int(max_pages) if max_pages else 2

    # Check cache first
    cache_key = _get_cache_key("pdf_attach", doctype, docname, max_pages)
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    # Get all PDF attachments
    attachments = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": doctype,
            "attached_to_name": docname
        },
        fields=["name", "file_name", "file_url", "is_private"]
    )

    result = []

    for attachment in attachments:
        file_name = attachment.get("file_name") or ""
        file_ext = file_name.split(".")[-1].lower() if file_name else ""

        # Only process PDF files
        if file_ext != "pdf":
            continue

        try:
            images = []

            # Try file path first
            file_url = attachment.get("file_url", "")
            file_path = _get_file_path_from_url(file_url)

            if not file_path or not os.path.exists(file_path):
                # Try to get from File doc
                file_doc = frappe.get_doc("File", attachment.get("name"))
                file_path = file_doc.get_full_path()

            if file_path and os.path.exists(file_path):
                images = _convert_pdf_to_images_optimized(
                    file_path,
                    max_pages=max_pages,
                    zoom=2.5,
                    jpeg_quality=85,
                    is_bytes=False
                )

            # Fallback: read file content as bytes via Frappe File doc
            if not images:
                try:
                    file_doc = frappe.get_doc("File", attachment.get("name"))
                    content = file_doc.get_content()
                    if content:
                        if isinstance(content, str):
                            content = content.encode("latin-1")
                        images = _convert_pdf_to_images_optimized(
                            content,
                            max_pages=max_pages,
                            zoom=2.5,
                            jpeg_quality=85,
                            is_bytes=True
                        )
                except Exception:
                    pass

            if images:
                result.append({
                    "file_name": file_name,
                    "images": images,
                    "page_count": len(images)
                })

        except Exception as e:
            frappe.log_error(
                f"Error converting PDF to images: {file_name}\n{str(e)}\n{frappe.get_traceback()}",
                "PDF to Image Conversion"
            )

    # Cache result for 5 minutes
    if result:
        frappe.cache().set_value(cache_key, result, expires_in_sec=3600)

    return result


@frappe.whitelist()
def get_invoice_attachment_images(invoice_name, max_pages=2):
    """
    Wrapper function to get PDF attachments as images for a Purchase Invoice.
    OPTIMIZED: Uses max_pages=2 default for faster loading.

    Args:
        invoice_name: The Purchase Invoice name
        max_pages: Maximum pages to convert per PDF (default: 2)

    Returns:
        List of base64 image strings
    """
    if not invoice_name:
        return []

    pdf_data = get_pdf_as_images("Purchase Invoice", invoice_name, max_pages)

    # Flatten all images into a single list
    all_images = []
    for pdf in pdf_data:
        all_images.extend(pdf.get("images", []))

    return all_images


# ──────────────────────────── Reference doctype → actual Frappe doctype mapping
REFERENCE_DOCTYPE_MAP = {
    "Purchase Invoice": "Purchase Invoice",
    "Debit Note": "Purchase Invoice",
    "Credit Note": "Sales Invoice",
    "Sales Invoice": "Sales Invoice",
    "Expense Claim": "Expense Claim",
    "Employee Advance": "Employee Advance",
    "Payment Entry": "Payment Entry",
    "Journal Entry": "Journal Entry",
    "Purchase Order": "Purchase Order",
}


@frappe.whitelist()
def get_invoice_preview_data(reference_doctype, reference_name, max_pages=3, parent_docname=None, row_idx=None):
    """Return attachment images, file list, and print preview separately for the hover popup.

    Enhanced (Issue 4): Also returns linked Purchase Order and Costing Sheet attachment
    when the parent PRF docname and row index are provided.
    """
    if not reference_doctype or not reference_name:
        return {"attachment_images": [], "file_list": [], "print_images": [], "po_images": [], "po_name": "", "costing_images": [], "costing_url": ""}

    actual_doctype = REFERENCE_DOCTYPE_MAP.get(reference_doctype, reference_doctype)
    max_pages = int(max_pages) if max_pages else 3

    # 1) Get all file attachments
    attachments = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": actual_doctype,
            "attached_to_name": reference_name,
        },
        fields=["file_name", "file_url", "is_private"],
    )

    # 2) Convert PDF attachments to images
    att_images = []
    pdf_data = get_pdf_as_images(actual_doctype, reference_name, max_pages)
    for pdf in pdf_data:
        att_images.extend(pdf.get("images", []))

    # 3) Direct image attachments
    IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp"}
    for att in attachments:
        file_name = att.get("file_name") or ""
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if ext not in IMAGE_EXTS:
            continue
        try:
            img_bytes = None
            file_path = _get_file_path_from_url(att.get("file_url", ""))
            if file_path and os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    img_bytes = f.read()
            else:
                # Fallback: read via Frappe File doc
                file_doc = frappe.get_doc("File", {"file_url": att.file_url, "attached_to_doctype": actual_doctype, "attached_to_name": reference_name})
                content = file_doc.get_content()
                if content:
                    img_bytes = content if isinstance(content, bytes) else content.encode("latin-1")
            if img_bytes:
                mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
                img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                att_images.append(f"data:{mime};base64,{img_b64}")
        except Exception:
            pass

    # 4) File list (all attachments for download links)
    file_list = [{"file_name": a.file_name, "file_url": a.file_url} for a in attachments if a.file_url]

    # 5) Print format preview (always generate)
    print_images = get_print_format_as_images(actual_doctype, reference_name, max_pages=max_pages) or []

    # 6) Issue 4 — Linked Purchase Order preview (for Purchase Invoice references)
    po_images = []
    po_name = ""
    if actual_doctype == "Purchase Invoice":
        po_name = frappe.db.get_value(
            "Purchase Invoice Item",
            {"parent": reference_name},
            "purchase_order",
            order_by="idx asc",
        ) or ""
        if po_name:
            po_images = get_print_format_as_images("Purchase Order", po_name, max_pages=max_pages, print_format="Avientek PO") or []

    # 7) Issue 4 — Costing Sheet attachment from the PRF row
    costing_images = []
    costing_url = ""
    if parent_docname and row_idx:
        try:
            row_data = frappe.db.get_value(
                "Payment Request Reference",
                {"parent": parent_docname, "idx": int(row_idx)},
                ["costing_sheet_attachment", "previous_payment_details"],
                as_dict=True,
            )
            if row_data:
                costing_url = row_data.get("costing_sheet_attachment") or row_data.get("previous_payment_details") or ""
                if costing_url and costing_url.lower().endswith(".pdf"):
                    costing_images = _pdf_url_to_images(costing_url, max_pages=max_pages) or []
        except Exception:
            pass

    return {
        "attachment_images": att_images,
        "file_list": file_list,
        "print_images": print_images,
        "po_images": po_images,
        "po_name": po_name,
        "costing_images": costing_images,
        "costing_url": costing_url,
    }


def _pdf_url_to_images(file_url, max_pages=3):
    """Helper: convert a PDF file URL to base64 image list."""
    try:
        file_path = _get_file_path_from_url(file_url)
        if not file_path or not os.path.exists(file_path):
            return []
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
        return _convert_pdf_to_images_optimized(pdf_bytes, max_pages=max_pages)
    except Exception:
        return []


@frappe.whitelist()
def get_reference_attachment_images(reference_doctype, reference_name, max_pages=2):
    """
    Generic function to get ALL attachments (PDFs converted to images + direct images)
    from any reference document. OPTIMIZED with caching.

    Handles the mapping from PRF reference_doctype (e.g. "Credit Note") to actual
    Frappe doctype (e.g. "Sales Invoice").

    If no file attachments are found, falls back to rendering the document's
    own print format as images — so there is always something to show.

    Returns list of base64 image strings (flattened from all attachments).
    """
    if not reference_doctype or not reference_name:
        return []

    actual_doctype = REFERENCE_DOCTYPE_MAP.get(reference_doctype, reference_doctype)
    max_pages = int(max_pages) if max_pages else 2

    # Check cache first
    cache_key = _get_cache_key("ref_attach", reference_doctype, reference_name, max_pages)
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    all_images = []

    # 1) PDF attachments → convert to images (uses optimized helper with caching)
    pdf_data = get_pdf_as_images(actual_doctype, reference_name, max_pages)
    for pdf in pdf_data:
        all_images.extend(pdf.get("images", []))

    # 2) Direct image attachments (jpg, jpeg, png, gif, webp)
    IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp"}
    attachments = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": actual_doctype,
            "attached_to_name": reference_name,
        },
        fields=["file_name", "file_url", "is_private"],
    )
    for att in attachments:
        file_name = att.get("file_name") or ""
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if ext not in IMAGE_EXTS:
            continue

        file_path = _get_file_path_from_url(att.get("file_url", ""))
        if not file_path or not os.path.exists(file_path):
            continue

        try:
            with open(file_path, "rb") as f:
                img_bytes = f.read()
            mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")
            all_images.append(f"data:{mime};base64,{img_b64}")
        except Exception:
            pass

    # 3) Fallback: if no file attachments found, render the document's print format
    if not all_images:
        all_images = get_print_format_as_images(actual_doctype, reference_name, max_pages=max_pages)

    # Cache result for 5 minutes
    if all_images:
        frappe.cache().set_value(cache_key, all_images, expires_in_sec=3600)

    return all_images


@frappe.whitelist()
def get_print_format_as_images(doctype, docname, print_format=None, max_pages=2):
    """
    Render a document's print format to PDF and convert to images.
    OPTIMIZED: Uses caching, lower resolution (1.0x), JPEG quality 60.

    Args:
        doctype: The doctype to print
        docname: The document name
        print_format: The print format name (optional, uses default if not specified)
        max_pages: Maximum pages to convert (default: 2)

    Returns:
        List of base64 image strings
    """
    if not doctype or not docname:
        return []

    max_pages = int(max_pages) if max_pages else 2

    # Check cache first
    cache_key = _get_cache_key("print_fmt", doctype, docname, print_format or "default", max_pages)
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    try:
        # Generate PDF from print format
        pdf_content = frappe.get_print(
            doctype,
            docname,
            print_format=print_format,
            as_pdf=True
        )

        if not pdf_content:
            return []

        # Convert PDF pages to images (zoom=2.5 for crisp text, jpeg_quality=85)
        images = _convert_pdf_to_images_optimized(
            pdf_content,
            max_pages=max_pages,
            zoom=2.5,
            jpeg_quality=85,
            is_bytes=True
        )

        # Cache result for 1 hour
        if images:
            frappe.cache().set_value(cache_key, images, expires_in_sec=3600)

        return images

    except Exception as e:
        frappe.log_error(
            f"Error converting print format to images: {doctype} {docname}\n{str(e)}\n{frappe.get_traceback()}",
            "Print Format to Image Conversion"
        )
        return []


@frappe.whitelist()
def get_all_print_attachments(docname):
    """
    Batch pre-fetch ALL attachment images for a Payment Request Form in one call.
    This eliminates per-row frappe.call() in the Jinja template.

    Returns a dict with:
        - prev_payment_images: list of base64 images
        - ref_images: {row_idx: [base64 images]}
        - po_images: {row_idx: [base64 images]}
        - costing_images: {row_idx: [base64 images]}
        - bank_letter_images: [base64 images]
        - additional_doc_images: {row_idx: [base64 images]}
    """
    doc = frappe.get_doc("Payment Request Form", docname)
    result = {
        "prev_payment_images": [],
        "ref_images": {},
        "po_images": {},
        "costing_images": {},
        "bank_letter_images": [],
        "additional_doc_images": {},
    }

    # 1) Previous Payment Details (from first row)
    first_row = doc.payment_references[0] if doc.payment_references else None
    if first_row and first_row.previous_payment_details:
        result["prev_payment_images"] = get_attachment_as_images(
            first_row.previous_payment_details, max_pages=5
        ) or []

    # 2) Per-row: reference attachments, linked POs, costing sheets
    for idx, row in enumerate(doc.payment_references):
        # Reference document attachments
        if row.reference_doctype and row.reference_doctype != "Manual" and row.reference_name:
            ref_imgs = get_reference_attachment_images(
                row.reference_doctype, row.reference_name, max_pages=5
            ) or []
            if ref_imgs:
                result["ref_images"][str(idx)] = ref_imgs

        # Linked Purchase Orders (Supplier only)
        if doc.party_type == "Supplier" and row.reference_doctype in ["Purchase Invoice", "Debit Note"]:
            linked_po = get_linked_po_for_invoice(row.reference_name)
            if linked_po:
                po_imgs = get_print_format_as_images(
                    "Purchase Order", linked_po, print_format="Purchase Order - India", max_pages=5
                ) or []
                if po_imgs:
                    result["po_images"][str(idx)] = {"po_name": linked_po, "images": po_imgs}

            # Costing sheets
            if row.costing_sheet_attachment:
                cs_imgs = get_attachment_as_images(row.costing_sheet_attachment, max_pages=5) or []
                if cs_imgs:
                    result["costing_images"][str(idx)] = cs_imgs

    # 3) Bank letter
    if doc.bank_letter:
        result["bank_letter_images"] = get_attachment_as_images(doc.bank_letter, max_pages=5) or []

    # 4) Additional documents
    for idx, addl_doc in enumerate(doc.additional_documents or []):
        if addl_doc.attachment:
            addl_imgs = get_attachment_as_images(addl_doc.attachment, max_pages=10) or []
            if addl_imgs:
                result["additional_doc_images"][str(idx)] = {
                    "label": addl_doc.label or "Additional Document",
                    "images": addl_imgs,
                }

    return result


@frappe.whitelist()
def get_linked_po_for_invoice(invoice_name):
    """
    Get the Purchase Order linked to a Purchase Invoice.

    Args:
        invoice_name: The Purchase Invoice name

    Returns:
        Purchase Order name or None
    """
    if not invoice_name:
        return None

    # Get the first Purchase Order linked to this invoice
    purchase_order = frappe.db.get_value(
        "Purchase Invoice Item",
        {"parent": invoice_name},
        "purchase_order",
        order_by="idx asc"
    )

    return purchase_order


@frappe.whitelist()
def get_attachment_as_images(file_url, max_pages=2):
    """
    Convert a PDF attachment URL to base64 images.
    OPTIMIZED: Uses caching, lower resolution (1.0x), JPEG quality 60.

    Args:
        file_url: The file URL from an Attach field (e.g., /files/cost.png.pdf or /private/files/...)
        max_pages: Maximum pages to convert (default: 2)

    Returns:
        List of base64 image strings
    """
    if not file_url:
        return []

    # Only process PDF files
    if not file_url.lower().endswith('.pdf'):
        return []

    max_pages = int(max_pages) if max_pages else 2

    # Check cache first
    cache_key = _get_cache_key("attach", file_url, max_pages)
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    try:
        # Get the file path from URL
        file_path = _get_file_path_from_url(file_url)

        if not file_path or not os.path.exists(file_path):
            frappe.log_error(f"Attachment file not found: {file_url}", "Attachment to Image Conversion")
            return []

        # Convert PDF to images (zoom=2.5 for crisp text, jpeg_quality=85)
        images = _convert_pdf_to_images_optimized(
            file_path,
            max_pages=max_pages,
            zoom=2.5,
            jpeg_quality=85,
            is_bytes=False
        )

        # Cache result for 1 hour
        if images:
            frappe.cache().set_value(cache_key, images, expires_in_sec=3600)

        return images

    except Exception as e:
        frappe.log_error(
            f"Error converting attachment to images: {file_url}\n{str(e)}\n{frappe.get_traceback()}",
            "Attachment to Image Conversion"
        )
        return []
