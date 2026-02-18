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

@frappe.whitelist()
def get_outstanding_reference_documents(args):

    if isinstance(args, str):
        args = json.loads(args)

    if args.get("party_type") == "Supplier":
        supplier_status = get_supplier_block_status(args["party"])
        if supplier_status["on_hold"]:
            if supplier_status["hold_type"] == "All":
                return []
            elif supplier_status["hold_type"] == "Payments":
                if not supplier_status["release_date"] or getdate(nowdate()) <= supplier_status["release_date"]:
                    return []


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
        # Get all debit note voucher_nos already added (to avoid duplicates)
        existing_debit_notes = set()
        for row in filtered_rows:
            if row.get("voucher_type") == "Debit Note":
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

    return filtered_rows


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
def get_supplier_bank_details(supplier_name):
    if not supplier_name:
        return {}

    # Step 1: Get default (or first) bank account linked to the supplier
    bank_account = frappe.get_all("Bank Account",
        filters={
            "party_type": "Supplier",
            "party": supplier_name
        },
        fields=["name", "bank", "bank_account_no"],
        limit=1
    )

    if not bank_account:
        return {}

    bank_data = bank_account[0]

    # Step 2: Fetch the SWIFT code from the linked Bank doctype
    swift_code = frappe.db.get_value("Bank", bank_data.bank, "swift_number") if bank_data.get("bank") else None

    return {
        "bank_account_no": bank_data.get("bank_account_no"),
        "bank": bank_data.get("bank"),
        "swift_code": swift_code,
        "supplier_bank_account": bank_data.get("name")
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
        # Try the new professional print format first, fall back to old one
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

    # Output merged PDF
    output = io.BytesIO()
    merger.write(output)
    merger.close()
    output.seek(0)

    frappe.local.response.filename = f"{docname}_combined.pdf"
    frappe.local.response.filecontent = output.read()
    frappe.local.response.type = "download"


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

    for pe in payment_entries:
        # Get bank account details
        bank_name = ""
        beneficiary_account = ""
        debit_account_no = ""

        if pe.bank_account:
            bank_data = frappe.db.get_value(
                "Bank Account", pe.bank_account,
                ["bank", "bank_account_no"], as_dict=True
            )
            if bank_data:
                bank_name = bank_data.get("bank") or ""
                debit_account_no = bank_data.get("bank_account_no") or ""

        if pe.party_bank_account:
            party_bank_data = frappe.db.get_value(
                "Bank Account", pe.party_bank_account,
                ["bank_account_no", "iban"], as_dict=True
            )
            if party_bank_data:
                beneficiary_account = party_bank_data.get("iban") or party_bank_data.get("bank_account_no") or ""

        # Determine payment type (TT/TR based on mode_of_payment or reference)
        payment_type_code = "TR"  # Default to Transfer
        if pe.mode_of_payment:
            mop = pe.mode_of_payment.upper()
            if "TT" in mop or "TELEGRAPHIC" in mop:
                payment_type_code = "TT"
            elif "TR" in mop or "TRANSFER" in mop:
                payment_type_code = "TR"

        payment_history.append({
            "sl_no": 0,  # Will be set later
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

    for je in journal_entries:
        # Get bank and account details
        bank_name = ""
        debit_account_no = ""
        beneficiary_account = ""

        if je.bank_account:
            bank_data = frappe.db.get_value(
                "Bank Account", je.bank_account,
                ["bank", "bank_account_no"], as_dict=True
            )
            if bank_data:
                bank_name = bank_data.get("bank") or ""
                debit_account_no = bank_data.get("bank_account_no") or ""

        # Get supplier's default bank account
        supplier_bank = frappe.db.get_value(
            "Bank Account",
            {"party_type": "Supplier", "party": supplier, "is_default": 1},
            ["bank_account_no", "iban"],
            as_dict=True
        )
        if supplier_bank:
            beneficiary_account = supplier_bank.get("iban") or supplier_bank.get("bank_account_no") or ""

        # Get supplier name
        supplier_name = frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier

        # Determine payment type
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
            "beneficiary_account": beneficiary_account,
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


@frappe.whitelist()
def get_pdf_as_images(doctype, docname, max_pages=10):
    """
    Get PDF attachments for a document and convert them to base64 images.
    Returns a list of image data that can be embedded in print formats.

    Args:
        doctype: The doctype to fetch attachments from
        docname: The document name
        max_pages: Maximum number of pages to convert per PDF (default: 10)

    Returns:
        List of dicts with 'file_name' and 'images' (list of base64 image strings)
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        frappe.log_error("PyMuPDF (fitz) not installed. Cannot convert PDF to images.")
        return []

    if not doctype or not docname:
        return []

    max_pages = int(max_pages) if max_pages else 10

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
            # Get the file path
            file_url = attachment.get("file_url", "")

            if file_url.startswith("/private/"):
                file_path = frappe.get_site_path() + file_url
            elif file_url.startswith("/files/"):
                file_path = frappe.get_site_path("public") + file_url
            else:
                # Try to get from File doc
                file_doc = frappe.get_doc("File", attachment.get("name"))
                file_path = file_doc.get_full_path()

            if not os.path.exists(file_path):
                frappe.log_error(f"File not found: {file_path}", "PDF to Image Conversion")
                continue

            # Open PDF and convert pages to images
            pdf_document = fitz.open(file_path)
            images = []

            num_pages = min(pdf_document.page_count, max_pages)

            for page_num in range(num_pages):
                page = pdf_document.load_page(page_num)

                # Render page to image (2x resolution for better quality)
                zoom = 2.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)

                # Convert to PNG bytes
                img_bytes = pix.tobytes("png")

                # Convert to base64
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                images.append(f"data:image/png;base64,{img_base64}")

            pdf_document.close()

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

    return result


@frappe.whitelist()
def get_invoice_attachment_images(invoice_name, max_pages=5):
    """
    Wrapper function to get PDF attachments as images for a Purchase Invoice.
    This is specifically designed for use in print formats.

    Args:
        invoice_name: The Purchase Invoice name
        max_pages: Maximum pages to convert per PDF

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


@frappe.whitelist()
def get_print_format_as_images(doctype, docname, print_format=None, max_pages=10):
    """
    Render a document's print format to PDF and convert to images.
    This allows embedding print formats within other print formats.

    Args:
        doctype: The doctype to print
        docname: The document name
        print_format: The print format name (optional, uses default if not specified)
        max_pages: Maximum pages to convert

    Returns:
        List of base64 image strings
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        frappe.log_error("PyMuPDF (fitz) not installed. Cannot convert PDF to images.")
        return []

    if not doctype or not docname:
        return []

    max_pages = int(max_pages) if max_pages else 10

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

        # Open PDF from bytes and convert to images
        pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
        images = []

        num_pages = min(pdf_document.page_count, max_pages)

        for page_num in range(num_pages):
            page = pdf_document.load_page(page_num)

            # Render page to image (2x resolution for better quality)
            zoom = 2.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PNG bytes
            img_bytes = pix.tobytes("png")

            # Convert to base64
            img_base64 = base64.b64encode(img_bytes).decode("utf-8")
            images.append(f"data:image/png;base64,{img_base64}")

        pdf_document.close()

        return images

    except Exception as e:
        frappe.log_error(
            f"Error converting print format to images: {doctype} {docname}\n{str(e)}\n{frappe.get_traceback()}",
            "Print Format to Image Conversion"
        )
        return []


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
