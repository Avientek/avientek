# Copyright (c) 2023, Craft and contributors
# For license information, please see license.txt

import frappe
import io
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
        ple.company == args.get("company")  # ✅ Add this line
    ]


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
    for row in voucher_outstandings:
        voucher_type = row.get("voucher_type")
        voucher_no = row.get("voucher_no")

        try:
            invoice = frappe.get_doc(voucher_type, voucher_no)
            meta = frappe.get_meta(voucher_type)

            # Fallbacks for all voucher types
            row["bill_no"] = invoice.get("bill_no") or invoice.name
            row["posting_date"] = invoice.get("posting_date")
            row["invoice_amount"] = invoice.get("total") or invoice.get("grand_total")
            row["outstanding"] = invoice.get("base_total") or row.get("outstanding")
            row["total_amount"] = row["invoice_amount"]
            row["currency"] = invoice.get("currency")
            row["exchange_rate"] = invoice.get("conversion_rate")
            if voucher_type == "Purchase Invoice":
                purchase_order = frappe.get_value(
                    "Purchase Invoice Item",
                    {"parent": voucher_no},
                    "purchase_order",
                    order_by="idx asc"
                )
                row["document_reference"] = purchase_order


        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Error processing voucher {voucher_type} {voucher_no}")
    return voucher_outstandings

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
        print_format_pdf = frappe.get_print(
            "Payment Request Form",
            docname,
            print_format="PAYMENT VOUCHER",
            as_pdf=True
        )
        merger.append(io.BytesIO(print_format_pdf))
    except Exception as e:
        frappe.log_error(f"Error merging print format PDF: {e}")

    # Loop through references
    for row in doc.payment_references:
        voucher_no = row.reference_name

        # Purchase Invoice Attachment
        try:
            attachment = frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": "Purchase Invoice",
                    "attached_to_name": voucher_no
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
            frappe.log_error(f"Error fetching Purchase Invoice attachment for {voucher_no}: {e}")

        # Purchase Order & Quotation PDFs
        try:
            purchase_order = frappe.get_value(
                "Purchase Invoice Item",
                {"parent": voucher_no},
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
            frappe.log_error(f"Error fetching PO/Quotation PDFs for {voucher_no}: {e}")

    # Output merged PDF
    output = io.BytesIO()
    merger.write(output)
    merger.close()
    output.seek(0)

    frappe.local.response.filename = f"{docname}_combined.pdf"
    frappe.local.response.filecontent = output.read()
    frappe.local.response.type = "download"
