# Copyright (c) 2023, Craft and contributors
# For license information, please see license.txt

import frappe
import json
from frappe.model.document import Document
from frappe import ValidationError, _, qb, scrub, throw
from frappe.query_builder.functions import Sum
from frappe.query_builder.utils import DocType
from pypika import Order
from pypika.terms import ExistsCriterion
from frappe.query_builder import AliasedQuery, Criterion, Table
from erpnext.controllers.accounts_controller import (
	AccountsController,
	get_supplier_block_status,
	validate_taxes_and_charges,
)

class PaymentRequestForm(Document):
	def setUp(self):
		create_workflow()

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
				condition=doc.approved_amount > 0
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
				condition=doc.approved_amount > 0
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
				condition=doc.approved_amount > 0
			),
		)
		workflow.append(
			"transitions",
			dict(
				state="Rejected", action="Review", next_state="Pending", allowed="Accounts User", allow_self_approval=1
			),
		)
		workflow.insert(ignore_permissions=True)

@frappe.whitelist()
def get_outstanding_reference_documents(args):

	if isinstance(args, str):
		args = json.loads(args)

	supplier_status = get_supplier_block_status(args["party"])
	if supplier_status["on_hold"]:
		if supplier_status["hold_type"] == "All":
			return []
		elif supplier_status["hold_type"] == "Payments":
			if (
				not supplier_status["release_date"] or getdate(nowdate()) <= supplier_status["release_date"]
			):
				return []

	company_currency = frappe.get_cached_value("Company", args.get("company"), "default_currency")
	ple = qb.DocType("Payment Ledger Entry")

	common_filter = []
	common_filter.append(ple.party_type == 'Supplier')
	common_filter.append(ple.party == args.get("party"))


	query_voucher_amount = (
			qb.from_(ple)
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
		qb.from_(ple)
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


	cte_query_voucher_amount_and_outstanding = (
		qb.with_(query_voucher_amount, "vouchers")
		.with_(query_voucher_outstanding, "outstanding")
		.from_(AliasedQuery("vouchers"))
		.left_join(AliasedQuery("outstanding"))
		.on(
			(AliasedQuery("vouchers").account == AliasedQuery("outstanding").account)
			& (AliasedQuery("vouchers").voucher_type == AliasedQuery("outstanding").voucher_type)
			& (AliasedQuery("vouchers").voucher_no == AliasedQuery("outstanding").voucher_no)
			& (AliasedQuery("vouchers").party_type == AliasedQuery("outstanding").party_type)
			& (AliasedQuery("vouchers").party == AliasedQuery("outstanding").party)
		)
		.select(
			Table("vouchers").account,
			Table("vouchers").voucher_type,
			Table("vouchers").voucher_no,
			Table("vouchers").party_type,
			Table("vouchers").party,
			Table("vouchers").posting_date,
			Table("vouchers").amount.as_("invoice_amount"),
			Table("vouchers").amount_in_account_currency.as_("invoice_amount_in_account_currency"),
			Table("outstanding").amount.as_("outstanding"),
			Table("outstanding").amount_in_account_currency.as_("outstanding_in_account_currency"),
			(Table("vouchers").amount - Table("outstanding").amount).as_("paid_amount"),
			(
				Table("vouchers").amount_in_account_currency - Table("outstanding").amount_in_account_currency
			).as_("paid_amount_in_account_currency"),
			Table("vouchers").due_date,
			Table("vouchers").currency,
		)
		.having(
			qb.Field("outstanding_in_account_currency") > 0)
	)

	voucher_outstandings = cte_query_voucher_amount_and_outstanding.run(as_dict=True)

	return voucher_outstandings