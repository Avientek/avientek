// Copyright (c) 2023, Craft and contributors
// For license information, please see license.txt
{% include "erpnext/public/js/controllers/accounts.js" %}
frappe.provide("erpnext.accounts.dimensions");

frappe.ui.form.on('Payment Request Form', {
	supplier: function(frm) {
		if(frm.doc.supplier && frm.doc.company) {
			if(!frm.doc.posting_date) {
				frappe.msgprint(__("Please select Posting Date before selecting Party"))
				frm.set_value("party", "");
				return ;
			}

			let company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;

			return frappe.call({
				method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_party_details",
				args: {
					company: frm.doc.company,
					party_type: 'Supplier',
					party: frm.doc.supplier,
					date: frm.doc.posting_date,
					// cost_center: frm.doc.cost_center
				},
				callback: function(r, rt) {
					// console.log("r.message.r.message.r.message.r.message.",r.message)
					if(r.message) {
						frappe.run_serially([
							() => frm.set_value("supplier_balance", r.message.party_balance),
							() => frm.clear_table("references"),
							() => frm.set_df_property("party_balance", "options", r.message.party_account_currency),
							() => frm.set_df_property("total_outstanding_amount", "options", r.message.party_account_currency),
							() => frm.set_df_property("allocated_amount", "options", r.message.party_account_currency)
						]);
					}
				}
			});
		}
	},
	get_outstanding_invoice: function(frm) {
		frm.clear_table("payment_references");

		if(!frm.doc.supplier) {
			return;
		}

		var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
		var args = {
			"posting_date": frm.doc.posting_date,
			"company": frm.doc.company,
			"party": frm.doc.supplier
		}

		return  frappe.call({
			method: 'avientek.avientek.doctype.payment_request_form.payment_request_form.get_outstanding_reference_documents',
			args: {
				args:args
			},
			callback: function(r,rt) {
				if(r.message) {

					$.each(r.message, function(i, d) {
						var c = frm.add_child("payment_references");
						c.reference_doctype = d.voucher_type;
						c.reference_name = d.voucher_no;
						c.due_date = d.due_date
						c.total_amount = d.invoice_amount;
						c.outstanding_amount = d.outstanding;
						c.bill_no = d.bill_no;
						c.payment_term = d.payment_term;
						c.allocated_amount = d.allocated_amount;

					});
					frm.refresh_fields();
					frm.events.set_total_outstanding_amount(frm);
				}
			}
		});
	},

	set_total_outstanding_amount: function(frm) {
		console.log("outstanding_amount")
		var total_outstanding_amount = 0.0;
		var base_total_allocated_amount = 0.0;
		$.each(frm.doc.payment_references || [], function(i, row) {
			if (row.outstanding_amount) {
				total_outstanding_amount += flt(row.outstanding_amount);
				// base_total_allocated_amount += flt(flt(row.allocated_amount)*flt(row.exchange_rate),
				// 	precision("base_paid_amount"));
			}
		});
		console.log("outstanding_amount",total_outstanding_amount)
		frm.set_value("total_outstanding_amount", Math.abs(total_outstanding_amount));
		// frm.set_value("base_total_allocated_amount", Math.abs(base_total_allocated_amount));
	},



	check_mandatory_to_fetch: function(frm) {
		$.each(["Company", "Supplier"], function(i, field) {
			if(!frm.doc[frappe.model.scrub(field)]) {
				frappe.msgprint(__("Please select {0} first", [field]));
				return false;
			}

		});
	}
});
