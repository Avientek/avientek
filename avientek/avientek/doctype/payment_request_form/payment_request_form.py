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


# Fields protected against post-submit edits — only Finance Manager /
# Finance Controller / System Manager may change them once the doc has
# been submitted. Everyone else has to Cancel and Amend, so the change
# is recorded in the audit trail.
_PRF_LOCKED_FIELDS_AFTER_SUBMIT = (
	# party block
	"party_type", "party", "party_name",
	"supplier_address", "address_display", "email", "telephone",
	# issued bank block
	"issued_bank", "account", "account_no",
	# beneficiary bank block
	"supplier_bank_account", "account_number", "iban", "bank",
	"swift_code", "bank_letter",
)
_PRF_BANK_EDIT_ROLES = {"Finance Manager", "Finance Controller", "System Manager"}


class PaymentRequestForm(Document):
	def validate(self):
		self._guard_bank_edits_after_submit()
		self._set_internal_transfer_title()
		self._dedupe_attachments()

	def _dedupe_attachments(self):
		"""Sammish 2026-05-16 (Jithin #3): bank letters / supplier docs
		were ending up as multiple identical File records attached to
		the PRF (same file_url, same parent). Root cause varies — user
		uploading via both the Attach field AND the sidebar widget,
		legacy auto-fetch flows from Supplier master, or PRFs amended
		from older versions.

		On save, remove redundant File rows: for each unique
		(attached_to_name, file_url) pair keep the OLDEST row (the
		original upload) and delete the rest. Safe — File records
		share file_url across rows; the underlying disk file is only
		removed when its LAST reference is deleted.

		Idempotent and silent: no-op when there are no duplicates.
		"""
		if self.is_new() or not self.name:
			return
		try:
			rows = frappe.get_all(
				"File",
				filters={
					"attached_to_doctype": "Payment Request Form",
					"attached_to_name": self.name,
				},
				fields=["name", "file_url", "creation"],
				order_by="creation asc",
			)
		except Exception:
			return
		seen = set()
		for r in rows:
			key = (r.file_url or "").strip()
			if not key:
				continue
			if key in seen:
				# Duplicate — delete this redundant pointer row.
				try:
					frappe.delete_doc("File", r.name, ignore_permissions=True, force=True)
				except Exception:
					# Never let a deletion failure break PRF save.
					pass
			else:
				seen.add(key)

	def _set_internal_transfer_title(self):
		"""Sammish 2026-05-16 (Jithin #7): Internal Transfer vouchers
		have no party / party_name, so the list view title column and
		the form breadcrumb both render blank. Auto-fill party_name with
		a descriptive label "Internal Transfer: <issued_bank> → <receiving_bank>"
		so list view + title behave for IT type too.

		Pay / Advance Pay rows are left untouched (party_name fetched
		from the actual Supplier/Customer/Employee).
		"""
		if (self.payment_type or "") != "Internal Transfer":
			return
		# Never overwrite a non-IT label that the user has set manually
		# (e.g. they typed a remark into party_name).
		current = (self.party_name or "").strip()
		if current and not current.startswith("Internal Transfer"):
			return
		issued = (self.issued_bank or "").strip() or "—"
		receiving = (self.receiving_bank or "").strip() or "—"
		self.party_name = f"Internal Transfer: {issued} → {receiving}"

	def _guard_bank_edits_after_submit(self):
		if self.is_new() or self.docstatus != 1:
			return
		before = self.get_doc_before_save()
		if not before or getattr(before, "docstatus", 0) != 1:
			return  # first-time submit, not an update-after-submit
		user_roles = set(frappe.get_roles(frappe.session.user))
		if user_roles & _PRF_BANK_EDIT_ROLES:
			return  # privileged — skip
		changed = []
		for fn in _PRF_LOCKED_FIELDS_AFTER_SUBMIT:
			before_val = before.get(fn) or ""
			after_val = self.get(fn) or ""
			if before_val != after_val:
				changed.append(fn)
		if changed:
			frappe.throw(
				_("Only Finance Manager or Finance Controller can change {0} "
				  "on a submitted Payment Request Form. "
				  "Cancel and Amend the document to revise these fields.").format(
					", ".join(changed)
				)
			)


def _get_workflow_signers(doc):
	"""For #10 — build a dict of workflow_state → {full_name, user, date}
	by walking the Version history. Only the FIRST time each state was
	entered counts (so a Reject → Revise → Authorise cycle keeps the
	current Authorised signer, not the old cancelled one)."""
	signers = {}
	if not doc or not doc.get("name"):
		return signers
	try:
		versions = frappe.get_all(
			"Version",
			filters={"ref_doctype": "Payment Request Form", "docname": doc.name},
			fields=["owner", "data", "creation"],
			order_by="creation asc",
		)
	except Exception:
		return signers
	for v in versions:
		try:
			payload = frappe.parse_json(v.data or "{}")
		except Exception:
			continue
		for change in (payload.get("changed") or []):
			if not isinstance(change, (list, tuple)) or len(change) < 3:
				continue
			if change[0] != "workflow_state":
				continue
			new_state = change[2]
			if not new_state:
				continue
			# Keep the MOST RECENT entry per state so rejections/revisions
			# don't show a stale signer
			full_name = frappe.db.get_value("User", v.owner, "full_name") or v.owner
			signers[new_state] = {
				"user": v.owner,
				"full_name": full_name,
				"date": v.creation,
			}
	return signers
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


def _get_outstanding_party_journal_entries(args):
    """Generic JV-by-party fetcher (Sridhar 2026-05-09).

    Mirrors _get_outstanding_employee_journal_entries but works for any
    party_type (Supplier / Customer / Employee). Returns one row per
    (Journal Entry, currency) pair where the JE has a credit (or debit
    for Customer payable side) on the requested party.

    For Supplier and Employee: company OWES them — pull rows where the
    party's account row has a CREDIT.
    For Customer: OWES the company — pull rows where the party's
    account row has a DEBIT.
    """
    from frappe.utils import flt

    party = args.get("party")
    party_type = args.get("party_type")
    company = args.get("company")
    if not party or not company or not party_type:
        return []

    company_currency = frappe.get_cached_value(
        "Company", company, "default_currency"
    )

    # Direction depends on party_type
    if party_type == "Customer":
        amount_field = "debit_in_account_currency"
        base_field = "debit"
    else:
        amount_field = "credit_in_account_currency"
        base_field = "credit"

    je_accounts = frappe.get_all(
        "Journal Entry Account",
        filters={
            "party_type": party_type,
            "party": party,
            amount_field: [">", 0],
            "docstatus": 1,
        },
        fields=["parent", amount_field, base_field, "account_currency",
                 "exchange_rate"],
    )

    rows = []
    seen_je = set()
    for jea in je_accounts:
        if jea.parent in seen_je:
            continue
        seen_je.add(jea.parent)

        je = frappe.get_doc("Journal Entry", jea.parent)
        if je.company != company or je.docstatus != 1:
            continue

        # Same Payment Ledger Entry offset check used for employees —
        # if the JE has been fully reconciled, skip it.
        try:
            ple_outstanding = frappe.db.sql(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM `tabPayment Ledger Entry`
                WHERE against_voucher_type = 'Journal Entry'
                AND against_voucher_no = %s
                AND party_type = %s
                AND party = %s
                AND delinked = 0
                """,
                (je.name, party_type, party),
            )[0][0] or 0
        except Exception:
            ple_outstanding = None

        # Group party-row totals by account currency so multi-currency JEs
        # produce one row per currency.
        currency_groups = {}
        for acc in je.accounts:
            if acc.party_type != party_type or acc.party != party:
                continue
            amt_fc = flt(getattr(acc, amount_field, 0))
            amt_base = flt(getattr(acc, base_field, 0))
            if amt_fc <= 0:
                continue
            curr = acc.account_currency or company_currency
            grp = currency_groups.setdefault(curr, {
                "amount": 0, "base_amount": 0,
                "exchange_rate": flt(acc.exchange_rate) or 1,
            })
            grp["amount"] += amt_fc
            grp["base_amount"] += amt_base

        if ple_outstanding is not None and abs(ple_outstanding) < 0.01:
            ple_has_entries = frappe.db.exists(
                "Payment Ledger Entry",
                {"voucher_no": je.name, "party": party, "delinked": 0},
            )
            if ple_has_entries:
                continue

        for curr, data in currency_groups.items():
            if data["amount"] <= 0:
                continue
            rows.append({
                "voucher_type": "Journal Entry",
                "voucher_no": je.name,
                # Bill_no / reference_name stay blank for JV (no supplier
                # invoice number for journal entries) — user can type a
                # remark if needed.
                "bill_no": "",
                "posting_date": je.posting_date,
                "due_date": je.posting_date,
                "grand_total": data["amount"],
                "base_grand_total": data["base_amount"],
                "outstanding": data["amount"],
                "base_outstanding": data["base_amount"],
                "currency": curr,
                "exchange_rate": data["exchange_rate"],
                "is_return": 0,
                "return_against": "",
                "document_reference": je.name,
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

    # Sridhar 2026-05-09: when payment_type='Advance Pay' AND the user
    # is fetching Purchase Invoices, also include outstanding Purchase
    # Orders. Advance Pay can be against either a PI or an open PO that
    # hasn't been invoiced yet. Pay flow stays PI-only per Jithin's
    # 2026-05-07 fix (commit 36a4aa4) — no PO/JV pollution there.
    if (
        args.get("reference_doctype") == "Purchase Invoice"
        and (args.get("payment_type") or "") == "Advance Pay"
    ):
        po_rows = _get_outstanding_purchase_orders(args)
        filtered_rows.extend(po_rows)

    # Sridhar 2026-05-09: also include outstanding Journal Entries
    # against the party when fetching Purchase Invoices (for Supplier)
    # or Sales Invoices (for Customer). These represent JV-recorded
    # receivables/payables that need to be paid. Skip for Pay flow if
    # we're matching the same "no JV pollution" rule — but Sridhar
    # explicitly asked for JV inclusion via Get Outstanding Invoice.
    if args.get("reference_doctype") in ("Purchase Invoice", "Sales Invoice"):
        je_rows = _get_outstanding_party_journal_entries(args)
        filtered_rows.extend(je_rows)

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

    if bank_account:
        bank_data = bank_account[0]
        swift_code = ""
        if bank_data.get("bank"):
            swift_code = frappe.db.get_value("Bank", bank_data.bank, "swift_number") or ""
        # SWIFT fallback — some sites store the SWIFT in branch_code.
        if not swift_code and bank_data.get("branch_code"):
            swift_code = bank_data.get("branch_code") or ""
        return {
            "bank_account_no": bank_data.get("bank_account_no") or "",
            "iban": bank_data.get("iban") or "",
            "bank": bank_data.get("bank") or "",
            "branch_code": bank_data.get("branch_code") or "",
            "swift_code": swift_code,
            "supplier_bank_account": bank_data.get("name") or "",
        }

    # Employee fallback — many HR setups don't create a Bank Account record
    # per employee; bank info lives directly on the Employee doc
    # (bank_name, bank_ac_no, iban). Use those so the PRF form fills in
    # automatically without manual entry.
    if party_type == "Employee":
        emp = frappe.db.get_value(
            "Employee",
            supplier_name,
            ["bank_name", "bank_ac_no", "iban"],
            as_dict=True,
        ) or {}
        if emp.get("bank_name") or emp.get("bank_ac_no") or emp.get("iban"):
            swift_code = ""
            if emp.get("bank_name"):
                swift_code = (
                    frappe.db.get_value("Bank", emp.get("bank_name"), "swift_number")
                    or ""
                )
            return {
                "bank_account_no": emp.get("bank_ac_no") or "",
                "iban": emp.get("iban") or "",
                "bank": emp.get("bank_name") or "",
                "branch_code": "",
                "swift_code": swift_code,
                "supplier_bank_account": "",
            }

    return {}


@frappe.whitelist()
def get_employee_contact_details(employee):
    """Return Employee's embedded address + contact fields for PRF
    onload. Employees usually don't have linked Address docs — their
    contact info sits directly on the Employee master."""
    if not employee:
        return {}
    emp = frappe.db.get_value(
        "Employee",
        employee,
        [
            "current_address",
            "permanent_address",
            "personal_email",
            "company_email",
            "prefered_email",
            "cell_number",
            "employee_name",
        ],
        as_dict=True,
    ) or {}
    if not emp:
        return {}
    address_display = emp.get("current_address") or emp.get("permanent_address") or ""
    email = (
        emp.get("prefered_email")
        or emp.get("company_email")
        or emp.get("personal_email")
        or ""
    )
    return {
        "address_display": address_display,
        "email": email,
        "telephone": emp.get("cell_number") or "",
        "employee_name": emp.get("employee_name") or "",
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


def _read_local_pdf(file_url):
    """Read a Frappe-managed file straight from disk — avoids the
    HTTP+session round-trip that the original sync downloader used.
    Works inside background jobs too (no request context required)."""
    if not file_url or not file_url.lower().endswith(".pdf"):
        return None
    try:
        from frappe.utils.file_manager import get_file_path
        path = get_file_path(file_url)
        if not path or not os.path.exists(path):
            return None
        with open(path, "rb") as fh:
            return fh.read()
    except Exception as e:
        frappe.log_error(f"_read_local_pdf failed for {file_url}: {e}")
        return None


def _build_combined_pdf_bytes(docname, progress_cb=None):
    """Builds the merged Payment Voucher PDF and returns the bytes.

    Pure (no HTTP context required), so the same function works whether
    called inline or from a background worker. Heavy steps:
      - Render Payment Voucher print format (~5s)
      - Per reference: render PO + Quotation print formats (~5-10s each)
      - Read attached PDFs from disk (instant, no HTTP)
    For large vouchers this can run 60s+, so callers should usually
    invoke this from inside frappe.enqueue.

    progress_cb(current, total, stage_msg) fires after each stage so the
    UI can render a live progress bar with stage breakdown.
    """
    import traceback
    import time as _time

    doc = frappe.get_doc("Payment Request Form", docname)
    merger = PdfMerger()
    appended = 0  # track sections actually merged so we can fail loud on empty output

    # Precompute total stage count so the progress bar shows a stable denominator.
    ref_count = len(doc.payment_references or [])
    addl_count = sum(1 for a in (doc.additional_documents or []) if a.attachment)
    bank_letter_count = 1 if doc.bank_letter else 0

    # Sammish 2026-05-15: PRF sidebar attachments (Files uploaded
    # directly on the form, e.g. supplier bank letter) get bundled at
    # the very end of the combined PDF. The auto-generated
    # <docname>_combined.pdf is filtered out to avoid recursing
    # yesterday's bundle into today's.
    _sidebar_files_all = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Payment Request Form",
            "attached_to_name": docname,
        },
        fields=["file_name", "file_url"],
        order_by="creation asc",
    ) or []
    _combined_self_name = f"{docname}_combined.pdf"
    # Sammish 2026-05-16: also exclude doc.bank_letter from the sidebar
    # loop. Without this, Jithin saw the bank letter appear TWICE in the
    # combined PDF — once via step 3 (the explicit doc.bank_letter
    # append) and once via step 5 (the sidebar pass picking up the same
    # File record because users upload bank_letter via the Attachments
    # widget which also creates a File row attached to the PRF).
    # Additional documents are similarly de-duped: skip any sidebar
    # file whose file_url matches an Additional Documents row.
    _bank_letter_url = (doc.bank_letter or "").strip()
    _addl_doc_urls = {
        (a.attachment or "").strip()
        for a in (doc.additional_documents or [])
        if a.attachment
    }
    sidebar_pdfs = [
        f for f in _sidebar_files_all
        if (f.file_name or "").strip() != _combined_self_name
        and (f.file_url or "").lower().endswith(".pdf")
        and (f.file_url or "").strip() != _bank_letter_url
        and (f.file_url or "").strip() not in _addl_doc_urls
    ]
    sidebar_count = len(sidebar_pdfs)

    total_stages = 1 + (3 * ref_count) + bank_letter_count + addl_count + sidebar_count
    _stage_counter = {"n": 0}

    def _step(msg):
        _stage_counter["n"] += 1
        if progress_cb:
            try:
                progress_cb(_stage_counter["n"], total_stages, msg)
            except Exception:
                pass

    def _announce(msg):
        """Emit a progress event at the CURRENT stage (don't advance the
        counter). Used to show the user what's happening BEFORE the heavy
        step completes, so long-running phases don't look frozen."""
        if progress_cb:
            try:
                progress_cb(_stage_counter["n"], total_stages, msg)
            except Exception:
                pass

    # 1. Payment Voucher print format (with format fallbacks). This step
    # is MANDATORY — if we can't render the voucher itself there is no
    # point saving a combined PDF at all. Let the exception propagate
    # to the worker's outer handler so the user sees the real error via
    # prf_combined_pdf_failed rather than an empty file.
    print_format_name = "Payment Voucher Fast"
    if not frappe.db.exists("Print Format", print_format_name):
        print_format_name = "Payment Voucher Professional"
    if not frappe.db.exists("Print Format", print_format_name):
        print_format_name = "PAYMENT VOUCHER"

    _announce(_("Rendering Payment Voucher…"))
    t_voucher = _time.time()
    pdf_bytes = frappe.get_print(
        "Payment Request Form", docname,
        print_format=print_format_name, as_pdf=True,
    )
    print(f"[PRF PDF {docname}] voucher '{print_format_name}' rendered in {_time.time()-t_voucher:.2f}s")
    if not pdf_bytes:
        raise RuntimeError(
            f"frappe.get_print returned empty bytes for Payment Request Form {docname} "
            f"using print format {print_format_name!r}"
        )
    merger.append(io.BytesIO(pdf_bytes))
    appended += 1
    _step(_("Rendered Payment Voucher"))

    # 2. Per-reference: PI attachment + PO PDF + Quotation PDF
    #
    # Optimization: the *same* Purchase Order and *same* Quotation often
    # appear across several Payment References (e.g. one PO invoiced in
    # multiple tranches). Rendering them once per reference is the
    # dominant cost for a big PRF — AVFZC-017 saw 13+ min. Below we:
    #
    #   (a) Resolve PI / PO / Quotation names per reference up-front
    #       (cheap SQL; surfaces which renders are actually needed).
    #   (b) Render each UNIQUE PO and Quotation exactly once and cache
    #       the bytes.
    #   (c) Assemble in original reference order from the caches.
    #
    # Additional timing instrumentation prints per-step elapsed seconds
    # into the worker log so future slowdowns are diagnosable without
    # re-reading the code. _time is already imported at the top of the
    # function so we don't re-import here.

    refs = list(doc.payment_references or [])

    # Sammish 2026-05-14: a PRF reference row carries:
    #   - reference_doctype (Purchase Invoice / Debit Note / Sales Invoice /
    #     Credit Note / Journal Entry / Payment Entry / Purchase Order /
    #     Sales Order / Delivery Note / Manual)
    #   - document_reference  (system pointer to the actual doc — set by
    #     the post-2026-05-09 picker)
    #   - reference_name      (legacy supplier-invoice-number field; for
    #     Purchase Invoice / Debit Note rows it's the bill_no that maps
    #     back to a PI via {bill_no: ...} lookup)
    #
    # Previous _resolve_ref only handled the Purchase Invoice case AND
    # used reference_name directly. For a Journal Entry row,
    # reference_name is None → the {bill_no: None} lookup matched the
    # FIRST Purchase Invoice with a blank bill_no on prod, and that
    # unrelated invoice's PO + Quotation got merged into the combined
    # PDF. Jithin saw an irrelevant PO appear in AVLLC-00936's combined
    # PDF (Haibu Space rent invoice / JV).
    #
    # This rewrite:
    #   1. Guards every lookup against null inputs.
    #   2. Picks the right source-doc per `reference_doctype`.
    #   3. Returns the set of file_urls attached to whichever doc the
    #      row really points at (JV / SI / DN / PE / PO / SO included).
    #   4. Keeps the PI-only PO + Quotation chain (so Get Outstanding
    #      Invoice flows still bundle the originating PO/QN).
    REFERENCE_TARGET_DOCTYPE = {
        "Purchase Invoice": "Purchase Invoice",
        "Debit Note":       "Purchase Invoice",
        "Sales Invoice":    "Sales Invoice",
        "Credit Note":      "Sales Invoice",
        "Journal Entry":    "Journal Entry",
        "Payment Entry":    "Payment Entry",
        "Purchase Order":   "Purchase Order",
        "Sales Order":      "Sales Order",
        "Delivery Note":    "Delivery Note",
    }

    def _resolve_ref(row):
        """Lightweight SQL-only resolve for one reference row.
        Returns dict with target_doctype, target_name, file_urls list,
        and the downstream PO + Quotation if the source is a Purchase
        Invoice.
        """
        out = {
            "target_doctype": None,
            "target_name": None,
            "file_urls": [],
            "po": None,
            "qn": None,
            # legacy keys kept for back-compat with any downstream caller
            "pi": None,
            "pi_att": None,
        }
        ref_doctype = (row.reference_doctype or "").strip()
        if ref_doctype == "Manual" or not ref_doctype:
            return out

        target_doctype = REFERENCE_TARGET_DOCTYPE.get(ref_doctype)
        if not target_doctype:
            return out

        # Canonical name resolution:
        #   - Purchase Invoice / Debit Note: prefer document_reference
        #     (which is the PI doctype name set by the picker). Fall back
        #     to looking up by bill_no = reference_name for legacy rows
        #     where document_reference was empty.
        #   - All others: use document_reference (the picker's system
        #     pointer).
        target_name = (row.document_reference or "").strip() or None

        if not target_name and target_doctype == "Purchase Invoice":
            # Legacy path — bill_no lookup. Only attempt when
            # reference_name is non-empty (the NULL match caused
            # cross-contamination from unrelated PIs).
            bill = (row.reference_name or "").strip()
            if bill:
                target_name = frappe.db.get_value(
                    "Purchase Invoice", {"bill_no": bill}, "name"
                )

        if not target_name:
            return out

        # Verify the doc actually exists (defensive — a stale
        # document_reference shouldn't crash the merger).
        if not frappe.db.exists(target_doctype, target_name):
            frappe.log_error(
                f"PRF combined PDF — stale reference: {target_doctype} {target_name!r} "
                f"on row {row.idx} of {row.parent} not found",
                "PRF Combined PDF",
            )
            return out

        out["target_doctype"] = target_doctype
        out["target_name"] = target_name

        # Read all attached files on that doc, oldest first.
        try:
            atts = frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": target_doctype,
                    "attached_to_name": target_name,
                },
                fields=["file_url"],
                order_by="creation asc",
            )
            out["file_urls"] = [a["file_url"] for a in atts if a.get("file_url")]
        except Exception as e:
            frappe.log_error(
                f"PRF combined PDF — attachment lookup {target_doctype} {target_name}: {e}\n{traceback.format_exc()}",
                "PRF Combined PDF",
            )

        # PI-only: derive the originating PO and Quotation so we can
        # bundle them after the PI attachment (existing behaviour).
        if target_doctype == "Purchase Invoice":
            out["pi"] = target_name  # back-compat
            out["pi_att"] = _read_local_pdf(out["file_urls"][0]) if out["file_urls"] else None
            out["po"] = frappe.get_value(
                "Purchase Invoice Item",
                {"parent": target_name},
                fieldname="purchase_order",
                order_by="idx asc",
            )
            if out["po"]:
                so = frappe.db.get_value(
                    "Purchase Order Item", {"parent": out["po"]}, "sales_order"
                )
                if so:
                    out["qn"] = frappe.db.get_value(
                        "Sales Order Item", {"parent": so}, "prevdoc_docname"
                    )
        return out

    t_resolve = _time.time()
    resolved = [_resolve_ref(row) for row in refs]
    print(f"[PRF PDF {docname}] resolved {len(refs)} refs in {_time.time()-t_resolve:.2f}s")

    # Unique PO / Quotation names to render exactly once.
    unique_pos = []
    seen_pos = set()
    for r in resolved:
        if r["po"] and r["po"] not in seen_pos:
            seen_pos.add(r["po"])
            unique_pos.append(r["po"])

    unique_qns = []
    seen_qns = set()
    for r in resolved:
        if r["qn"] and r["qn"] not in seen_qns:
            seen_qns.add(r["qn"])
            unique_qns.append(r["qn"])

    po_pdf_cache = {}
    for _i, po in enumerate(unique_pos, start=1):
        _announce(_("Rendering Purchase Order {0}/{1} — {2}").format(_i, len(unique_pos), po))
        t = _time.time()
        try:
            po_pdf_cache[po] = get_pdf(
                frappe.get_print("Purchase Order", po, print_format="Avientek PO")
            )
            print(f"[PRF PDF {docname}] rendered PO {po} in {_time.time()-t:.2f}s")
        except Exception as e:
            frappe.log_error(
                f"PRF combined PDF — PO render {po}: {e}\n{traceback.format_exc()}",
                "PRF Combined PDF",
            )

    qn_pdf_cache = {}
    for _i, qn in enumerate(unique_qns, start=1):
        _announce(_("Rendering Quotation {0}/{1} — {2}").format(_i, len(unique_qns), qn))
        t = _time.time()
        try:
            qn_pdf_cache[qn] = get_pdf(
                frappe.get_print("Quotation", qn, print_format="Quotation New")
            )
            print(f"[PRF PDF {docname}] rendered QN {qn} in {_time.time()-t:.2f}s")
        except Exception as e:
            frappe.log_error(
                f"PRF combined PDF — Quotation render {qn}: {e}\n{traceback.format_exc()}",
                "PRF Combined PDF",
            )

    # Assemble in original reference order, reusing cached bytes.
    # Sammish 2026-05-14: PI rows still get their full 3-stage chain
    # (PI attachment → PO PDF → Quotation PDF). All other reference
    # types (JV, PE, SI, SO, DN, PO-direct) get their attached files
    # merged in; the second + third progress steps are emitted as
    # "(n/a)" so the bar still ticks predictably.
    for _ref_idx, (row, r) in enumerate(zip(refs, resolved), start=1):
        ref_type_lbl = (row.reference_doctype or "Manual").strip() or "Manual"
        if not r["target_doctype"]:
            _step(_("Reference {0}/{1} — {2} attachment (skipped)").format(_ref_idx, ref_count, ref_type_lbl))
            _step(_("Reference {0}/{1} — Purchase Order (n/a)").format(_ref_idx, ref_count))
            _step(_("Reference {0}/{1} — Quotation (n/a)").format(_ref_idx, ref_count))
            continue

        # Step (a) — attached files on the source doc (whichever type).
        for fu in r["file_urls"]:
            pdf_bytes = _read_local_pdf(fu)
            if pdf_bytes:
                merger.append(io.BytesIO(pdf_bytes))
                appended += 1
        _step(_("Reference {0}/{1} — {2} attachment").format(_ref_idx, ref_count, ref_type_lbl))

        # Steps (b)+(c) — only for Purchase Invoice rows, chain into
        # the originating PO + Quotation. Other reference types stop
        # at attachments.
        if r["target_doctype"] == "Purchase Invoice" and r["po"]:
            po_pdf = po_pdf_cache.get(r["po"])
            if po_pdf:
                merger.append(io.BytesIO(po_pdf))
                appended += 1
            _step(_("Reference {0}/{1} — Purchase Order").format(_ref_idx, ref_count))

            if r["qn"]:
                q_pdf = qn_pdf_cache.get(r["qn"])
                if q_pdf:
                    merger.append(io.BytesIO(q_pdf))
                    appended += 1
                _step(_("Reference {0}/{1} — Quotation").format(_ref_idx, ref_count))
            else:
                _step(_("Reference {0}/{1} — Quotation (none)").format(_ref_idx, ref_count))
        else:
            _step(_("Reference {0}/{1} — Purchase Order (n/a)").format(_ref_idx, ref_count))
            _step(_("Reference {0}/{1} — Quotation (n/a)").format(_ref_idx, ref_count))

    print(
        f"[PRF PDF {docname}] reference summary — refs={len(refs)} "
        f"unique_POs={len(unique_pos)} unique_QNs={len(unique_qns)}"
    )

    # 3. Bank letter
    if doc.bank_letter:
        pdf_bytes = _read_local_pdf(doc.bank_letter)
        if pdf_bytes:
            merger.append(io.BytesIO(pdf_bytes))
            appended += 1
        _step(_("Bank letter"))

    # 4. Additional documents (Additional Documents child table)
    for addl in (doc.additional_documents or []):
        if not addl.attachment:
            continue
        pdf_bytes = _read_local_pdf(addl.attachment)
        if pdf_bytes:
            merger.append(io.BytesIO(pdf_bytes))
            appended += 1
        _step(_("Additional document"))

    # 5. PRF sidebar attachments (uploaded via the Attachments widget,
    # e.g. "Yealink Bank Details letter.pdf"). Sammish 2026-05-15:
    # Jithin reported these were missing from Download Combined PDF.
    # Filtering of the auto-generated <docname>_combined.pdf is done
    # above in the sidebar_pdfs precompute so we don't recurse.
    for f in sidebar_pdfs:
        pdf_bytes = _read_local_pdf(f.file_url)
        if pdf_bytes:
            merger.append(io.BytesIO(pdf_bytes))
            appended += 1
        _step(_("PRF attachment — {0}").format(f.file_name or f.file_url))

    if appended == 0:
        raise RuntimeError(
            f"Combined PDF would be empty for Payment Request Form {docname} — "
            "no voucher / references / attachments could be merged. Check the "
            "Error Log doctype for per-step failure details."
        )

    _announce(_("Merging PDFs…"))
    t_merge = _time.time()
    output = io.BytesIO()
    merger.write(output)
    merger.close()
    output.seek(0)
    data = output.read()
    print(f"[PRF PDF {docname}] merged {appended} sections in {_time.time()-t_merge:.2f}s, output={len(data)} bytes")
    return data


def _build_and_attach_combined_pdf(docname, user):
    """Background-job target. Builds the combined PDF, deletes any
    previous "<docname>_combined.pdf" attached to the same PRF, attaches
    the fresh one, and pushes a realtime event so the UI can refresh
    and surface a download button."""
    import traceback

    # Impersonate the requesting user so print formats render with the
    # same permissions the user has on the form (e.g. linked PI/PO/QTN
    # read access). Without this the worker runs as Administrator but
    # certain custom print formats / hooks resolve blank when session
    # user is 'Administrator' in a queue context — reported symptom:
    # downloaded combined PDF opens as a blank page.
    try:
        if user:
            frappe.set_user(user)
    except Exception as e:
        frappe.log_error(
            f"PRF combined PDF — set_user({user}) failed: {e}",
            "PRF Combined PDF",
        )

    def _progress(current, total, stage):
        try:
            frappe.publish_realtime(
                "prf_combined_pdf_progress",
                {
                    "docname": docname,
                    "current": current,
                    "total": total,
                    "stage": stage,
                },
                user=user,
            )
        except Exception:
            pass

    # Immediately emit a "worker picked up the job" event so the UI knows
    # the build has truly started (vs. stuck in the queue).
    _progress(0, 1, _("Worker started — preparing build plan…"))

    import time as _time
    t_overall = _time.time()
    try:
        pdf_bytes = _build_combined_pdf_bytes(docname, progress_cb=_progress)
        print(f"[PRF PDF {docname}] build_bytes total: {_time.time()-t_overall:.2f}s")
        filename = f"{docname}_combined.pdf"

        # Remove any older combined PDF attached to this PRF so the user
        # always sees the latest one only — avoids attachment clutter.
        old_files = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Payment Request Form",
                "attached_to_name": docname,
                "file_name": filename,
            },
            fields=["name"],
        )
        for f in old_files:
            try:
                frappe.delete_doc("File", f.name, ignore_permissions=True, force=True)
            except Exception:
                pass

        _progress(1, 1, _("Attaching PDF to Payment Request Form…"))
        t_save = _time.time()
        # save_file enforces frappe.conf.max_file_size (default 10 MB).
        # Combined PDFs that merge many references routinely exceed 10 MB —
        # AVFZC-017 reported "File size exceeded the maximum allowed size
        # of 10.0 MB". Temporarily raise the ceiling for this attach only,
        # then restore, so the limit still applies to user uploads.
        _orig_max = frappe.local.conf.get("max_file_size") if getattr(frappe.local, "conf", None) else None
        try:
            if getattr(frappe.local, "conf", None) is not None:
                try:
                    frappe.local.conf["max_file_size"] = 200 * 1024 * 1024  # 200 MB
                except TypeError:
                    # Some Frappe versions use a _dict that only supports attribute access.
                    setattr(frappe.local.conf, "max_file_size", 200 * 1024 * 1024)
            file_doc = save_file(
                fname=filename,
                content=pdf_bytes,
                dt="Payment Request Form",
                dn=docname,
                is_private=1,
            )
        finally:
            if getattr(frappe.local, "conf", None) is not None:
                try:
                    if _orig_max is not None:
                        frappe.local.conf["max_file_size"] = _orig_max
                    else:
                        frappe.local.conf.pop("max_file_size", None)
                except Exception:
                    pass
        frappe.db.commit()
        print(f"[PRF PDF {docname}] save_file + commit: {_time.time()-t_save:.2f}s")

        frappe.publish_realtime(
            "prf_combined_pdf_ready",
            {"docname": docname, "file_url": file_doc.file_url, "file_name": filename},
            user=user,
        )

        # System notification (also surfaces in the bell icon)
        try:
            frappe.publish_realtime(
                "msgprint",
                _("Combined PDF for {0} is ready. Refresh the form to see it under Attachments.").format(docname),
                user=user,
            )
        except Exception:
            pass
    except Exception as e:
        tb = traceback.format_exc()
        frappe.log_error(
            f"PRF combined PDF — background build failed for {docname}: {e}\n{tb}",
            "PRF Combined PDF",
        )
        frappe.publish_realtime(
            "prf_combined_pdf_failed",
            {"docname": docname, "error": str(e)[:800]},
            user=user,
        )


@frappe.whitelist()
def download_payment_pdf(docname, mode="enqueue"):
    """Combined Payment Voucher PDF.

    mode="enqueue" (default) — queues the build on a background worker
    and returns immediately so the HTTP gateway doesn't time out on
    large vouchers. The worker attaches the resulting PDF to the PRF
    and emits a realtime event "prf_combined_pdf_ready".

    mode="sync" — legacy behavior; streams the PDF inline. Only safe
    for small vouchers (<3 references) since render time can exceed the
    Frappe Cloud gateway timeout.
    """
    if not frappe.has_permission("Payment Request Form", "read", doc=docname):
        frappe.throw(_("Not permitted"))

    if mode == "sync":
        pdf_bytes = _build_combined_pdf_bytes(docname)
        frappe.local.response.filename = f"{docname}_combined.pdf"
        frappe.local.response.filecontent = pdf_bytes
        frappe.local.response.type = "download"
        return

    # Default: background mode. enqueue_after_commit was removed — the
    # endpoint does no prior DB write, so there's nothing to commit; on
    # some Frappe Cloud deployments the job was never getting queued
    # (reported on Jithin's spreadsheet row 30).
    job = frappe.enqueue(
        "avientek.avientek.doctype.payment_request_form.payment_request_form._build_and_attach_combined_pdf",
        queue="long",
        timeout=900,
        docname=docname,
        user=frappe.session.user,
    )
    # Remember this job so a subsequent "Cancel" click can kill it.
    # Scoped per-docname, auto-expires after 1 hour.
    try:
        if job and getattr(job, "id", None):
            frappe.cache().set_value(
                f"prf_combined_pdf_job:{docname}",
                job.id,
                expires_in_sec=3600,
            )
    except Exception:
        pass

    return {
        "status": "queued",
        "job_id": getattr(job, "id", None) if job else None,
        "message": _("Combined PDF for {0} is being prepared. You'll see it under Attachments shortly.").format(docname),
    }


@frappe.whitelist()
def cancel_combined_pdf(docname):
    """Stop a running Combined PDF build job for this PRF.

    Looks up the RQ job id we stashed at enqueue time and asks RQ to
    stop it (sends SIGINT to the worker processing that job). Also
    publishes prf_combined_pdf_failed so any listening UI clears its
    banner. Idempotent — if the job is already gone, just clears UI.
    """
    if not frappe.has_permission("Payment Request Form", "read", doc=docname):
        frappe.throw(_("Not permitted"))

    cache_key = f"prf_combined_pdf_job:{docname}"
    job_id = None
    try:
        job_id = frappe.cache().get_value(cache_key)
        if isinstance(job_id, bytes):
            job_id = job_id.decode("utf-8", errors="ignore")
    except Exception:
        job_id = None

    cancelled = False
    err = None
    if job_id:
        # Try two mechanisms: rq.command.send_stop_job_command (interrupts a
        # running job in-flight) and rq.cancel_job (removes a queued job).
        try:
            import rq  # noqa: F401
            from rq import cancel_job as _cancel_queued
            from rq.command import send_stop_job_command as _stop_running
            conn = frappe.cache().redis
            try:
                _stop_running(conn, job_id)
                cancelled = True
            except Exception as e1:
                err = str(e1)
            try:
                _cancel_queued(job_id, connection=conn)
                cancelled = True
            except Exception as e2:
                if not cancelled:
                    err = f"{err}; {e2}" if err else str(e2)
        except Exception as e:
            err = str(e)

    # Clear the cache entry either way.
    try:
        frappe.cache().delete_value(cache_key)
    except Exception:
        pass

    # Notify the UI to clear the banner (even if job was already dead).
    try:
        frappe.publish_realtime(
            "prf_combined_pdf_failed",
            {
                "docname": docname,
                "error": _("Build cancelled by user."),
            },
            user=frappe.session.user,
        )
    except Exception:
        pass

    return {
        "cancelled": bool(cancelled),
        "job_id": job_id,
        "error": err,
    }


@frappe.whitelist()
def get_voucher_print_data(docname):
    """
    Single consolidated method for the Payment Voucher print format.
    Fetches all data needed in one call to avoid multiple round-trips from Jinja.
    """
    doc = frappe.get_doc("Payment Request Form", docname)

    company_currency = frappe.db.get_value("Company", doc.company, "default_currency") or "AED"

    # Supplier/party bank details — full fallback chain so print never
    # comes out blank when a Bank Account record is missing or SWIFT
    # isn't on the Bank doc:
    #   1. doc.supplier_bank_account (explicit selection on the form)
    #   2. is_default Bank Account for that party
    #   3. ANY Bank Account for that party
    #   4. Employee.bank_name/bank_ac_no/iban (HR setups w/o Bank Accounts)
    # SWIFT comes from Bank.swift_number, falling back to
    # Bank Account.branch_code.
    supplier_bank = {}
    if doc.get("supplier_bank_account"):
        supplier_bank = frappe.db.get_value(
            "Bank Account", doc.supplier_bank_account,
            ["name", "bank", "bank_account_no", "iban", "branch_code"],
            as_dict=True,
        ) or {}
    if not supplier_bank:
        supplier_bank = frappe.db.get_value(
            "Bank Account",
            {"party_type": doc.party_type, "party": doc.party, "is_default": 1},
            ["name", "bank", "bank_account_no", "iban", "branch_code"],
            as_dict=True,
        ) or {}
    if not supplier_bank:
        supplier_bank = frappe.db.get_value(
            "Bank Account",
            {"party_type": doc.party_type, "party": doc.party},
            ["name", "bank", "bank_account_no", "iban", "branch_code"],
            as_dict=True,
        ) or {}
    if not supplier_bank and doc.party_type == "Employee":
        emp = frappe.db.get_value(
            "Employee", doc.party,
            ["bank_name", "bank_ac_no", "iban"],
            as_dict=True,
        ) or {}
        if emp.get("bank_name") or emp.get("bank_ac_no") or emp.get("iban"):
            supplier_bank = {
                "name": "",
                "bank": emp.get("bank_name") or "",
                "bank_account_no": emp.get("bank_ac_no") or "",
                "iban": emp.get("iban") or "",
                "branch_code": "",
            }

    supplier_swift = ""
    if supplier_bank and supplier_bank.get("bank"):
        supplier_swift = (
            frappe.db.get_value("Bank", supplier_bank.get("bank"), "swift_number") or ""
        )
    if not supplier_swift and supplier_bank and supplier_bank.get("branch_code"):
        supplier_swift = supplier_bank.get("branch_code") or ""

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


def _classify_payment_type(mode_of_payment):
    """Map a Mode of Payment label to the short code shown in the
    Previous Payment History table on PRF print formats and the form
    popup. Sridhar 2026-05-05 #11: previous code defaulted everything
    to "TR" and only overrode for TT/TELEGRAPHIC modes — Cheque, Cash,
    LC, Advance, Online etc. all rendered as "TR" which confused users.

    Mapping is keyword-based on the upper-cased mode string. Order
    matters — first match wins. Falls back to the first 4 alpha chars
    of the mode as a generic short code, or "PAY" if mode is blank.
    """
    if not mode_of_payment:
        return "PAY"
    mop = mode_of_payment.upper()
    # Order matters — more specific patterns first. "LETTER" contains the
    # substring "TT", so the LC rule must run before the TT rule, or
    # Letter-of-Credit modes get misclassified as TT.
    rules = (
        (("LETTER OF CREDIT", "L/C", "LC ", "LC-"),    "LC"),
        (("TRUST RECEIPT", "TRUST", "TR ", "TR-"),     "TR"),
        (("TELEGRAPHIC", "WIRE", "SWIFT", "TT"),       "TT"),
        (("ADVANCE", "ADV "),                          "ADV"),
        (("CHEQUE", "CHQ", "CHECK"),                   "CHQ"),
        (("CASH",),                                    "CASH"),
        (("ONLINE", "PORTAL", "INTERNET"),             "ONL"),
        (("VISA", "MASTERCARD", "CREDIT CARD", "CARD"),"CARD"),
        (("BANK TRANSFER", "BT ", "NEFT", "RTGS",
          "IMPS", "ACH"),                              "BT"),
        (("DEMAND DRAFT", "DD"),                       "DD"),
    )
    for keywords, code in rules:
        if any(k in mop for k in keywords):
            return code
    # Fallback: first 4 alpha chars of the mode (safer than blank).
    short = "".join(ch for ch in mop if ch.isalpha())[:4]
    return short or "PAY"


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

        payment_type_code = _classify_payment_type(pe.mode_of_payment)

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

        payment_type_code = _classify_payment_type(je.mode_of_payment)

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


# ──────────────────────────── OPEN PURCHASE ORDER PULL (#3) ──────────
@frappe.whitelist()
def get_open_purchase_orders_for_party(company, party_type, party, currency=None):
    """Return open Purchase Orders for the given party (typically a
    Supplier). Used by the "Get Open Purchase Orders" button shown on
    Payment Request Form when payment_type = "Advance Pay" — lets the
    user pull POs into the Payment References table for advance payment.

    Filters:
      docstatus = 1
      status NOT IN ('Closed', 'Completed', 'Delivered')   ← still actionable
      total_billed_amt < grand_total                        ← not fully invoiced
      grand_total > 0
      company / supplier / (currency if provided) match
    """
    from frappe.utils import flt

    if not (company and party_type and party):
        return []
    if party_type != "Supplier":
        # Advance Pay → Open PO is supplier-flow only. Returning empty
        # avoids an inappropriate UI for Customer / Employee parties.
        return []

    where = [
        "docstatus = 1",
        "company = %s",
        "supplier = %s",
        "status NOT IN ('Closed', 'Completed', 'Delivered', 'Cancelled')",
        "grand_total > 0",
        # PO carries a per_billed percentage (Float 0..100). Anything < 100
        # is still partially-or-fully un-invoiced — eligible for advance.
        "IFNULL(per_billed, 0) < 100",
    ]
    args = [company, party]
    if currency:
        where.append("currency = %s")
        args.append(currency)

    rows = frappe.db.sql(
        f"""SELECT name, transaction_date, currency, conversion_rate,
                   grand_total, base_grand_total,
                   IFNULL(per_billed, 0) AS per_billed,
                   status, supplier, supplier_name
            FROM `tabPurchase Order`
            WHERE {' AND '.join(where)}
            ORDER BY transaction_date DESC, name DESC
            LIMIT 200""",
        args, as_dict=True,
    )
    for r in rows:
        billed_pct = flt(r["per_billed"])
        r["billed_pct"] = billed_pct
        r["billed_amt"] = flt(r["grand_total"]) * billed_pct / 100.0
        r["pending_amt"] = flt(r["grand_total"]) - r["billed_amt"]
    return rows


# ──────────────────────────── PARTY BALANCE IN DOC CURRENCY ───────────
@frappe.whitelist()
def get_party_balance_in_doc_currency(company, party_type, party, target_currency=None, posting_date=None):
    """Return the party's outstanding balance expressed in target_currency.

    Avientek 2026-04-27 #10: PRF was showing supplier balance in company
    currency, but users want it in the Document currency for consistency
    with the totals on the same form.

    Mechanism:
        1. ERPNext's get_party_details returns party_balance in COMPANY
           currency.
        2. If target_currency == company_currency (or empty), return the
           company-currency balance unchanged.
        3. Otherwise convert via Currency Exchange spot rate at
           posting_date (target_currency → company_currency, then divide).
    """
    from frappe.utils import flt
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_party_details

    if not (company and party_type and party):
        return 0
    try:
        pdetails = get_party_details(
            company=company, party_type=party_type, party=party,
            date=posting_date,
        ) or {}
    except Exception:
        pdetails = {}
    company_balance = flt(pdetails.get("party_balance") or pdetails.get("balance") or 0)

    company_currency = frappe.get_cached_value("Company", company, "default_currency")
    if not target_currency or target_currency == company_currency:
        return company_balance

    try:
        from erpnext.setup.utils import get_exchange_rate
        rate_target_to_company = flt(
            get_exchange_rate(target_currency, company_currency, posting_date)
        ) or 1.0
    except Exception:
        rate_target_to_company = 1.0

    if not rate_target_to_company:
        return company_balance
    return company_balance / rate_target_to_company


@frappe.whitelist()
def party_link_query(doctype, txt, searchfield, start, page_len, filters):
    """Custom Link-field query for the manual document picker on PRF.

    Frappe's standard Link query filters by parent-doc fields only. JV
    and PE keep `party` info on a child row (Journal Entry Account /
    or as `party` on PE parent), so passing supplier/customer in the
    standard `filters` dict doesn't work for these.

    This method handles the special doctypes by joining to the child
    table and filtering on `party`. For all other doctypes it falls
    back to the standard `frappe.client.get_list`-style query so the
    same JS code path works for every reference type.

    Sridhar 2026-05-09: triggered from the PRF reference picker JS.

    Args:
      doctype  : the picker's target doctype (Journal Entry, Payment
                 Entry, Purchase Invoice, etc.)
      filters  : dict — comes from JS get_query.  Custom keys we care
                 about:
                   _party        — string, the supplier/customer/employee
                   _party_type   — Supplier / Customer / Employee
                   _company      — company filter
                   _is_return    — 0/1 for PI / SI flavor split
                   _docstatus    — submit-only filter
    """
    import json as _json
    if isinstance(filters, str):
        try:
            filters = _json.loads(filters)
        except Exception:
            filters = {}
    filters = filters or {}
    party = filters.pop("_party", None)
    party_type = filters.pop("_party_type", None)
    company = filters.pop("_company", None)
    is_return = filters.pop("_is_return", None)
    ds = filters.pop("_docstatus", None)
    txt = (txt or "").strip()
    like = f"%{txt}%"

    if doctype == "Journal Entry":
        # Filter via child Journal Entry Account.party
        sql = """
            SELECT DISTINCT je.name, je.posting_date, je.user_remark
            FROM `tabJournal Entry` je
            INNER JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
            WHERE 1=1
        """
        params = []
        if company:
            sql += " AND je.company = %s"
            params.append(company)
        if ds in ("1", 1):
            sql += " AND je.docstatus = 1"
        elif ds in ("!=2", "not 2"):
            sql += " AND je.docstatus != 2"
        if party and party_type:
            sql += " AND jea.party_type = %s AND jea.party = %s"
            params.extend([party_type, party])
        if txt:
            sql += " AND (je.name LIKE %s OR je.user_remark LIKE %s)"
            params.extend([like, like])
        sql += " ORDER BY je.posting_date DESC, je.name DESC LIMIT %s, %s"
        params.extend([int(start or 0), int(page_len or 20)])
        return frappe.db.sql(sql, tuple(params))

    if doctype == "Payment Entry":
        # PE has party_type + party as parent fields.
        sql = """
            SELECT pe.name, pe.posting_date, pe.party_name
            FROM `tabPayment Entry` pe
            WHERE 1=1
        """
        params = []
        if company:
            sql += " AND pe.company = %s"
            params.append(company)
        if ds in ("1", 1):
            sql += " AND pe.docstatus = 1"
        elif ds in ("!=2", "not 2"):
            sql += " AND pe.docstatus != 2"
        if party and party_type:
            sql += " AND pe.party_type = %s AND pe.party = %s"
            params.extend([party_type, party])
        if txt:
            sql += " AND (pe.name LIKE %s OR pe.party_name LIKE %s)"
            params.extend([like, like])
        sql += " ORDER BY pe.posting_date DESC, pe.name DESC LIMIT %s, %s"
        params.extend([int(start or 0), int(page_len or 20)])
        return frappe.db.sql(sql, tuple(params))

    # Default: standard Link query — Frappe's get_link_value or
    # frappe.client.get_list flow works fine since the parent doctype
    # already has the party field (supplier / customer / employee).
    fr_filters = {}
    if company:
        fr_filters["company"] = company
    if party and party_type == "Supplier":
        fr_filters["supplier"] = party
    elif party and party_type == "Customer":
        fr_filters["customer"] = party
    elif party and party_type == "Employee":
        fr_filters["employee"] = party
    if ds in ("1", 1):
        fr_filters["docstatus"] = 1
    elif ds in ("!=2", "not 2"):
        fr_filters["docstatus"] = ["!=", 2]
    if is_return in ("1", 1):
        fr_filters["is_return"] = 1
    elif is_return in ("0", 0):
        fr_filters["is_return"] = 0
    # Workflow status exclusions matching the JS filters for the manual
    # picker. Mirrors the bulk-fetch exclusions so JV/PE custom-query
    # path returns the same actionable subset.
    if doctype == "Purchase Order":
        fr_filters["status"] = [
            "not in", ["Completed", "Cancelled", "Closed", "On Hold", "Delivered"]
        ]
    elif doctype in ("Purchase Invoice", "Sales Invoice"):
        fr_filters["status"] = ["not in", ["Paid", "Cancelled", "Return"]]
    if txt:
        fr_filters["name"] = ["like", like]
    rows = frappe.get_all(
        doctype,
        filters=fr_filters,
        fields=["name"],
        limit_start=int(start or 0),
        limit_page_length=int(page_len or 20),
        order_by="modified desc",
    )
    return [(r["name"],) for r in rows]


@frappe.whitelist()
def get_party_balance_with_jv_inclusion(company, party_type, party, target_currency=None, posting_date=None):
    """Like get_party_balance_in_doc_currency, plus any Journal Entry
    Account postings to the party's default receivable / payable account
    that DON'T have party_type/party fields populated on the JV row.

    Sridhar 2026-04-27 #4: "For Supplier / Employee etc, the Outstanding
    Balance from the journal Entries not reflecting". The most common
    cause: an accountant booked the JV using the supplier's payable GL
    account but forgot to set party_type=Supplier / party=<name> on the
    row. ERPNext's standard get_party_details only counts party-tagged
    rows, so those postings vanish from the balance.

    This helper sums the standard party-balance PLUS the loose JV
    postings to the same account, so the balance the user sees on the
    PRF reflects every JV that mentions their account, not just the
    well-tagged ones.

    Note: this does NOT alter ERPNext's GLE logic anywhere else (Aging,
    Trial Balance, etc.). It only feeds the supplier_balance field on
    Payment Request Form. Long-term the right fix is data hygiene: tag
    party_type/party on JV rows. This helper buys time while that
    cleanup happens.
    """
    from frappe.utils import flt, today as _today

    base = flt(get_party_balance_in_doc_currency(
        company, party_type, party, target_currency, posting_date
    ))

    if not (company and party_type and party):
        return base

    # Resolve the party's default account on this company (typically
    # default_payable_account for Supplier/Employee, default_receivable_account
    # for Customer). Use the standard ERPNext helper.
    try:
        from erpnext.accounts.party import get_party_account
        party_account = get_party_account(party_type, party, company)
    except Exception:
        party_account = None
    if not party_account:
        return base  # nothing to scan

    # Find loose JV postings to that account (party fields blank).
    on_or_before = posting_date or _today()
    rows = frappe.db.sql(
        """SELECT COALESCE(SUM(
                  IFNULL(jea.debit_in_account_currency, 0)
                - IFNULL(jea.credit_in_account_currency, 0)
              ), 0) AS net_company_currency
           FROM `tabJournal Entry Account` jea
           INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
           WHERE je.docstatus = 1
             AND je.posting_date <= %s
             AND jea.account = %s
             AND (jea.party IS NULL OR jea.party = '')
             AND (jea.party_type IS NULL OR jea.party_type = '')""",
        (on_or_before, party_account), as_dict=True,
    )
    loose_company_currency = flt(rows[0].net_company_currency if rows else 0)
    if not loose_company_currency:
        return base

    # JV postings are stored in the JV's account currency; we read the
    # *_in_account_currency column. For party accounts that match the
    # company's default currency, this equals company currency. Convert
    # to target_currency the same way the base balance was converted.
    company_currency = frappe.get_cached_value("Company", company, "default_currency")
    if not target_currency or target_currency == company_currency:
        # Loose JV posting is in payable-account currency; for typical
        # AED-account suppliers that's company currency already.
        return base + loose_company_currency

    try:
        from erpnext.setup.utils import get_exchange_rate
        rate_target_to_company = flt(get_exchange_rate(
            target_currency, company_currency, posting_date
        )) or 1.0
    except Exception:
        rate_target_to_company = 1.0
    if not rate_target_to_company:
        return base + loose_company_currency
    return base + (loose_company_currency / rate_target_to_company)


@frappe.whitelist()
def get_party_balance_cross_company(company, party_type, party,
                                     target_currency=None, posting_date=None):
    """Return the party's TOTAL outstanding balance across EVERY company
    they have GL postings in, expressed in target_currency.

    Sridhar 2026-05-05 #4: "Outstanding not fetching for other companies …
    if any balance is showing in outstanding those items should be
    fetched." For an Avientek-group supplier with payable rows in (say)
    Avientek FZCO + Avientek Trading LLC + Avientek Electronics Trading
    LLC, the PRF supplier_balance field used to show only the originating
    company's balance — the team had to look up the rest manually.

    Mechanism:
      1. Read tabGL Entry directly — covers every voucher type (PI, CrN,
         DrN, JV with party tagged, PE allocations, etc.). Uses
         account_currency column so amounts are already in the company
         account currency.
      2. Group by `company`. For each company, convert net (debit -
         credit) from that company's default currency to target_currency
         at posting_date FX.
      3. Sum across companies + add the loose-JV exposure for the calling
         company (preserves the existing `_with_jv_inclusion` behaviour
         on the originating company; cross-company JVs with party fields
         tagged are already in the GL Entry sweep).

    `company` is the ORIGINATING company (the PRF's company); we still
    keep it as required so the loose-JV scan stays scoped — those un-tagged
    JVs are an originating-company hygiene problem, not a cross-company one.

    Returns a single number (sum across companies), in target_currency.
    """
    from frappe.utils import flt

    if not (party_type and party):
        return 0

    # 1. Standard cross-company sweep via tabGL Entry. is_cancelled=0
    #    excludes voided rows. is_opening='No' would exclude opening
    #    balances — the customer wants ALL outstanding so we KEEP them.
    where = ["gle.party_type = %(pt)s",
             "gle.party = %(p)s",
             "gle.is_cancelled = 0"]
    if posting_date:
        where.append("gle.posting_date <= %(pd)s")
    rows = frappe.db.sql(
        f"""SELECT gle.company,
                   COALESCE(SUM(IFNULL(gle.debit_in_account_currency, 0)
                              - IFNULL(gle.credit_in_account_currency, 0)),
                            0) AS net_account_ccy,
                   gle.account_currency AS account_ccy
            FROM `tabGL Entry` gle
            WHERE {' AND '.join(where)}
            GROUP BY gle.company, gle.account_currency
            HAVING ABS(net_account_ccy) > 0.01""",
        {"pt": party_type, "p": party, "pd": posting_date},
        as_dict=True,
    )

    if not rows:
        # Nothing in GL — fall back to the loose-JV inclusive helper for
        # the originating company so callers still get a sensible number.
        return get_party_balance_with_jv_inclusion(
            company, party_type, party, target_currency, posting_date,
        )

    # 2. Convert each company-bucket to target_currency. Cache rates by
    #    (from_ccy → target) so we don't hit get_exchange_rate per row.
    target_currency = target_currency or frappe.get_cached_value(
        "Company", company, "default_currency"
    )
    rate_cache = {}
    try:
        from erpnext.setup.utils import get_exchange_rate
    except Exception:
        get_exchange_rate = None

    def _convert(amt, from_ccy):
        if not amt:
            return 0.0
        if not from_ccy or from_ccy == target_currency:
            return flt(amt)
        if not get_exchange_rate:
            return flt(amt)  # best-effort; better to over-estimate
        rate = rate_cache.get(from_ccy)
        if rate is None:
            try:
                rate = flt(get_exchange_rate(from_ccy, target_currency,
                                             posting_date)) or 1.0
            except Exception:
                rate = 1.0
            rate_cache[from_ccy] = rate
        return flt(amt) * rate

    grand_total = 0.0
    for r in rows:
        grand_total += _convert(r["net_account_ccy"], r["account_ccy"])

    # 3. Layer in the loose-JV adjustment for the originating company.
    #    GL sweep above already counts party-tagged JV rows; this just
    #    adds the un-tagged ones (the historical Avientek pattern).
    try:
        loose_addition = flt(get_party_balance_with_jv_inclusion(
            company, party_type, party, target_currency, posting_date,
        )) - flt(get_party_balance_in_doc_currency(
            company, party_type, party, target_currency, posting_date,
        ))
    except Exception:
        loose_addition = 0.0
    return grand_total + loose_addition


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

    # Supplier/party bank details — show for Supplier, Employee, Customer.
    # Cascaded fallback: explicit selection -> default Bank Account -> any
    # Bank Account -> (for Employee) the bank fields on the Employee doc
    # itself. The last fallback is new — on this site Employees have no
    # Bank Account records and their bank details live on Employee.bank_*,
    # so the print was showing blank for all Employee payments.
    supplier_bank = {}
    supplier_swift = ""
    if doc.payment_type != "Internal Transfer" and doc.party and doc.party_type:
        if doc.get("supplier_bank_account"):
            supplier_bank = frappe.db.get_value(
                "Bank Account",
                doc.supplier_bank_account,
                ["name", "bank", "bank_account_no", "iban", "branch_code"],
                as_dict=True,
            ) or {}
        if not supplier_bank:
            supplier_bank = frappe.db.get_value(
                "Bank Account",
                {"party_type": doc.party_type, "party": doc.party, "is_default": 1},
                ["name", "bank", "bank_account_no", "iban", "branch_code"],
                as_dict=True,
            ) or {}
        if not supplier_bank:
            supplier_bank = frappe.db.get_value(
                "Bank Account",
                {"party_type": doc.party_type, "party": doc.party},
                ["name", "bank", "bank_account_no", "iban", "branch_code"],
                as_dict=True,
            ) or {}
        # Employee bank fields fallback (bank_name / bank_ac_no / iban on
        # the Employee doc itself — used in HR setups that don't create
        # per-employee Bank Account records)
        if not supplier_bank and doc.party_type == "Employee":
            emp = frappe.db.get_value(
                "Employee", doc.party,
                ["bank_name", "bank_ac_no", "iban"],
                as_dict=True,
            ) or {}
            if emp.get("bank_name") or emp.get("bank_ac_no") or emp.get("iban"):
                supplier_bank = {
                    "name": "",
                    "bank": emp.get("bank_name") or "",
                    "bank_account_no": emp.get("bank_ac_no") or "",
                    "iban": emp.get("iban") or "",
                    "branch_code": "",
                }

        if supplier_bank and supplier_bank.get("bank"):
            supplier_swift = (
                frappe.db.get_value("Bank", supplier_bank["bank"], "swift_number") or ""
            )
        # SWIFT final fallback — some sites put the SWIFT code in
        # Bank Account.branch_code. If Bank.swift_number wasn't populated
        # but branch_code is, use that so the print isn't blank.
        if not supplier_swift and supplier_bank and supplier_bank.get("branch_code"):
            supplier_swift = supplier_bank.get("branch_code") or ""

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

        # bill_no = Supplier Invoice No (printed in Invoice column on
        # Payment Voucher per Sridhar 2026-04-27 #7). The PRF child stores
        # bill_no when populated (for Purchase Invoice + Debit Note); fall
        # back to reference_name (system ref) so the column never goes
        # blank for manual / non-PI rows.
        bill_no_value = (row.bill_no or "").strip() or row.reference_name or ""

        rows_data.append({
            "idx": row.idx,
            "reference_doctype": row.reference_doctype or "",
            "reference_name": row.reference_name or "",
            "bill_no": bill_no_value,
            "invoice_date": formatdate(row.invoice_date, "dd-MM-yy") if row.invoice_date else "",
            # Sridhar 2026-05-09: Due Date column added to PV Fast / Pro
            # invoice details table.
            "due_date": formatdate(row.due_date, "dd-MM-yy") if row.due_date else "",
            "currency": curr,
            "amount_fc": fmt_money(amount_fc, currency=curr),
            "amount_base": fmt_money(amount_base, currency=company_currency),
            # Reference and Remarks are kept SEPARATE per Sridhar 2026-04-27
            # #8. Earlier the template collapsed both into one column which
            # made the 'Remarks' column actually display reference numbers.
            "document_reference": row.document_reference or "",
            "remarks": row.remarks or "",
        })

    # Format currency totals
    formatted_currency_totals = []
    for curr, amount in currency_totals.items():
        formatted_currency_totals.append(fmt_money(amount, currency=curr))

    # TR/LC total — converted to the chosen TR currency so the printed
    # label and amount match (per Sridhar 2026-04-27 #6: "currency
    # showing company currency but amount is in Document currency").
    #
    # Sammish 2026-05-16 (Jithin #2): the TR Amount line on the printed
    # Payment Voucher must always read the DOCUMENT currency. When
    # doc.currency was somehow left blank on legacy / migrated PRFs the
    # old `doc.currency or company_currency` fallback printed the
    # company default (AED) even though the real TR loan was in another
    # currency. Fallback chain widened: doc.currency → issued_currency
    # (TR is paid out of the issued bank) → company_currency.
    #
    # Rule:
    #   tr_currency = doc.currency / issued_currency / company_currency
    #   For each row:
    #       - if row.currency == tr_currency: use outstanding_amount/grand_total as-is
    #       - else: use base_outstanding_amount/base_grand_total (in company currency)
    #         and divide by tr_currency-to-company exchange rate to express in tr_currency.
    #   This gives a single coherent total in tr_currency.
    tr_currency_for_total = doc.currency or doc.issued_currency or company_currency
    tr_total = 0.0
    for row in (doc.payment_references or []):
        row_curr = row.currency or company_currency
        row_fc = flt(row.outstanding_amount or row.grand_total or 0)
        row_base = flt(row.base_outstanding_amount or row.base_grand_total or 0)
        if row_curr == tr_currency_for_total:
            tr_total += row_fc
        elif tr_currency_for_total == company_currency:
            # row in foreign, target in company → use the base value
            tr_total += row_base
        else:
            # Both row & target are non-company; convert via the row's
            # base value and the target's spot rate to company.
            try:
                from erpnext.setup.utils import get_exchange_rate
                rate_target_to_company = flt(get_exchange_rate(
                    tr_currency_for_total, company_currency, doc.posting_date
                )) or 1.0
            except Exception:
                rate_target_to_company = 1.0
            tr_total += (row_base / rate_target_to_company) if rate_target_to_company else row_base

    # Pre-fetch ALL attachment images in one batch (avoids per-row frappe.call in Jinja)
    ref_label_map = {
        "Purchase Invoice": "Supplier Invoice", "Debit Note": "Debit Note",
        "Credit Note": "Credit Note", "Sales Invoice": "Sales Invoice",
        "Expense Claim": "Expense Claim", "Payment Entry": "Payment Entry",
        "Journal Entry": "Journal Entry", "Purchase Order": "Purchase Order"
    }
    # Sammish 2026-05-15: Resolve the canonical Frappe doc per row
    # BEFORE handing off to the attachment fetchers. Passing the
    # supplier's free-text proforma number (e.g. "#032079") to
    # frappe.get_print raises DoesNotExistError and silently buries the
    # bank-letter attachment that is actually attached to the REAL PO
    # (e.g. PO-FZCO-26-00556). Mirrors _build_combined_pdf_bytes._resolve_ref.
    _ref_target_doctype = {
        "Purchase Invoice": "Purchase Invoice",
        "Debit Note":       "Purchase Invoice",
        "Sales Invoice":    "Sales Invoice",
        "Credit Note":      "Sales Invoice",
        "Journal Entry":    "Journal Entry",
        "Payment Entry":    "Payment Entry",
        "Purchase Order":   "Purchase Order",
        "Sales Order":      "Sales Order",
        "Delivery Note":    "Delivery Note",
    }

    def _resolve_canonical(row):
        rdt = (row.reference_doctype or "").strip()
        if not rdt or rdt == "Manual":
            return None, None
        tgt = _ref_target_doctype.get(rdt)
        if not tgt:
            return None, None
        name = (row.document_reference or "").strip()
        if not name and tgt == "Purchase Invoice":
            bill = (row.reference_name or "").strip()
            if bill:
                name = frappe.db.get_value("Purchase Invoice", {"bill_no": bill}, "name")
        if not name or not frappe.db.exists(tgt, name):
            return None, None
        return tgt, name

    row_attachments = []
    for row in (doc.payment_references or []):
        row_data = {"ref_images": [], "po_images": [], "costing_images": [], "ref_label": "", "ref_name": "", "linked_po": ""}
        tgt_dt, tgt_name = _resolve_canonical(row)
        if tgt_dt and tgt_name:
            row_data["ref_label"] = ref_label_map.get(row.reference_doctype, row.reference_doctype)
            # User-facing ref label shows the canonical doc name (e.g.
            # "PO-FZCO-26-00556"), not the supplier proforma. The
            # supplier proforma is still shown in the Supplier Invoice
            # No column above.
            row_data["ref_name"] = tgt_name
            row_data["ref_images"] = get_reference_attachment_images(tgt_dt, tgt_name, max_pages=3) or []

            # Linked PO (supplier only). For PI rows, derive the PO from
            # the resolved canonical PI name (not from the freetext bill_no).
            if doc.party_type == "Supplier" and row.reference_doctype in ("Purchase Invoice", "Debit Note"):
                linked_po = get_linked_po_for_invoice(tgt_name)
                if linked_po:
                    row_data["linked_po"] = linked_po
                    row_data["po_images"] = get_print_format_as_images("Purchase Order", linked_po, print_format="Purchase Order - India", max_pages=3) or []

                # Costing sheet
                if row.costing_sheet_attachment:
                    row_data["costing_images"] = get_attachment_as_images(row.costing_sheet_attachment, max_pages=3) or []

        row_attachments.append(row_data)

    # Sammish 2026-05-15: PRF sidebar attachments — files uploaded via
    # the Attachments widget directly on the PRF (e.g. supplier bank
    # letter "Yealink Bank Details letter.pdf"). Previously these were
    # NOT included in either print or Combined PDF. Filter out the
    # auto-attached <docname>_combined.pdf so we don't recurse a
    # previous bundle into the new one.
    prf_attachments = []
    try:
        sidebar_files = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Payment Request Form",
                "attached_to_name": docname,
            },
            fields=["file_name", "file_url"],
            order_by="creation asc",
        ) or []
        combined_self_name = f"{docname}_combined.pdf"
        # Sammish 2026-05-16: same de-dup as combined PDF builder — the
        # bank letter and Additional Documents rows are rendered as
        # their own sections in the print, so picking them up again here
        # would print them twice.
        _print_bank_letter_url = (doc.bank_letter or "").strip()
        _print_addl_urls = {
            (a.attachment or "").strip()
            for a in (doc.additional_documents or [])
            if a.attachment
        }
        for f in sidebar_files:
            fname = (f.file_name or "").strip()
            furl = (f.file_url or "").strip()
            if fname == combined_self_name:
                continue
            if furl and furl == _print_bank_letter_url:
                continue
            if furl and furl in _print_addl_urls:
                continue
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext == "pdf":
                # Render PDF pages as images so they embed in the print
                # format like other attachment sections.
                images = []
                pdf_data = get_pdf_as_images("Payment Request Form", docname, max_pages=5) or []
                for pd in pdf_data:
                    if pd.get("file_name") == fname:
                        images = pd.get("images") or []
                        break
                if images:
                    prf_attachments.append({"file_name": fname, "images": images})
            elif ext in ("jpg", "jpeg", "png", "gif", "webp"):
                imgs = get_attachment_as_images(f.file_url, max_pages=1) or []
                if imgs:
                    prf_attachments.append({"file_name": fname, "images": imgs})
    except Exception:
        # Never let attachment fetch failures break the voucher print.
        prf_attachments = []

    # Signers for the signature block in print (#10)
    signers = _get_workflow_signers(doc)
    prepared_by_name = (
        frappe.db.get_value("User", doc.owner, "full_name") if doc.owner else ""
    ) or (doc.owner or "")

    # Signature image lookup from Avientek Settings → signature_images.
    # Map keyed on signature_key (workflow role label or free-form name).
    # Each value: {"name": <display name>, "designation": <text>, "image": <url>}.
    # Also auto-attach image to dynamic signers when linked_user matches the
    # signing user — so a workflow Approved-by user gets their image rendered
    # without having to maintain a per-role row.
    signature_images = {}
    try:
        sett = frappe.get_cached_doc("Avientek Settings")
        for row in (sett.get("signature_images") or []):
            key = (row.signature_key or "").strip()
            if not key or not row.image:
                continue
            signature_images[key] = {
                "name": row.signer_name or "",
                "designation": row.designation or "",
                "image": row.image,
                "linked_user": row.linked_user or "",
            }
        # Hydrate each signer dict with .signature_image when we can find one.
        # Priority: linked_user match → role label match → none.
        user_to_image = {
            v["linked_user"]: v["image"]
            for v in signature_images.values() if v.get("linked_user")
        }
        for role_label, sig in (signers or {}).items():
            if not isinstance(sig, dict):
                continue
            user_email = sig.get("user") or sig.get("email") or ""
            if user_email and user_email in user_to_image:
                sig["signature_image"] = user_to_image[user_email]
            elif role_label in signature_images:
                sig["signature_image"] = signature_images[role_label]["image"]
    except Exception:
        signature_images = {}

    return {
        "company_currency": company_currency,
        "issued_bank_details": issued_bank_details,
        "receiving_bank_details": receiving_bank_details,
        "supplier_bank": supplier_bank,
        "supplier_swift": supplier_swift,
        "signers": signers,
        "signature_images": signature_images,
        "prepared_by_name": prepared_by_name,
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
        # Always matches the currency tr_total was summed in (see TR/LC
        # block above) so the printed label and amount stay coherent.
        "tr_currency": tr_currency_for_total,
        "posting_date_fmt": formatdate(doc.posting_date, "d-M-yyyy") if doc.posting_date else "",
        "cheque_date_fmt": formatdate(doc.cheque_date, "d-M-yyyy") if doc.cheque_date else "",
        "issued_amount_fmt": fmt_money(flt(doc.issued_amount or 0), currency=doc.issued_currency or company_currency),
        "receiving_amount_fmt": fmt_money(flt(doc.receiving_amount or 0), currency=doc.receiving_currency or company_currency),
        "row_attachments": row_attachments,
        # Sammish 2026-05-15: sidebar attachments uploaded directly to
        # the PRF (not to a linked reference). Rendered at the end of
        # the print format after row_attachments.
        "prf_attachments": prf_attachments,
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

# Sridhar 2026-05-11: legacy PRF rows can carry a reference_doctype that
# doesn't match the doctype the document_reference name actually belongs
# to (e.g. row says "Purchase Order" but document_reference is a Sales
# Order ID). Without a fallback, View / Open Form / Print View build a
# 404 URL. We probe these doctypes in order whenever the stated doctype
# doesn't contain the name.
_DOCTYPE_PROBE_ORDER = (
    "Purchase Invoice",
    "Sales Invoice",
    "Purchase Order",
    "Sales Order",
    "Delivery Note",
    "Journal Entry",
    "Payment Entry",
    "Employee Advance",
    "Expense Claim",
    "Quotation",
)


def _resolve_actual_doctype(reference_doctype, reference_name):
    """Return the doctype where `reference_name` actually exists.

    Tries the mapped doctype first; on miss, scans common transactional
    doctypes. Returns the original mapped doctype if nothing matches so
    callers degrade gracefully.
    """
    if not reference_name:
        return REFERENCE_DOCTYPE_MAP.get(reference_doctype, reference_doctype)
    mapped = REFERENCE_DOCTYPE_MAP.get(reference_doctype, reference_doctype)
    if mapped and frappe.db.exists(mapped, reference_name):
        return mapped
    for dt in _DOCTYPE_PROBE_ORDER:
        if dt == mapped:
            continue
        try:
            if frappe.db.exists(dt, reference_name):
                return dt
        except Exception:
            continue
    return mapped


@frappe.whitelist()
def resolve_reference_doctype(reference_doctype, reference_name):
    """Public resolver for JS callers (drilldown click / View button).

    Returns {"actual_doctype": "...", "exists": bool, "stated_doctype": "..."}.
    """
    actual = _resolve_actual_doctype(reference_doctype, reference_name)
    exists = bool(reference_name and actual and frappe.db.exists(actual, reference_name))
    return {
        "stated_doctype": reference_doctype or "",
        "actual_doctype": actual or "",
        "exists": exists,
    }


@frappe.whitelist()
def get_invoice_preview_data(reference_doctype, reference_name, max_pages=3, parent_docname=None, row_idx=None):
    """Return attachment images, file list, and print preview separately for the hover popup.

    Enhanced (Issue 4): Also returns linked Purchase Order and Costing Sheet attachment
    when the parent PRF docname and row index are provided.
    """
    if not reference_doctype or not reference_name:
        return {"attachment_images": [], "file_list": [], "print_images": [], "po_images": [], "po_name": "", "costing_images": [], "costing_url": "", "resolved_doctype": "", "resolved_exists": False}

    actual_doctype = _resolve_actual_doctype(reference_doctype, reference_name)
    resolved_exists = bool(actual_doctype and frappe.db.exists(actual_doctype, reference_name))
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
        "resolved_doctype": actual_doctype or "",
        "resolved_exists": resolved_exists,
        "stated_doctype": reference_doctype or "",
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

    # Sammish 2026-05-15: skip silently when the doc doesn't exist.
    # Without this guard, frappe.get_print() raises DoesNotExistError
    # which msgprints "<doctype> <docname> not found" into the response
    # message_log BEFORE our try/except swallows the exception. The
    # message then surfaces as a popup on the print page (Jithin's bug
    # report on AVFZC-02138: row had reference_name="#032079", which is
    # the supplier's free-text proforma number, not a Frappe doc name).
    if not frappe.db.exists(doctype, docname):
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
