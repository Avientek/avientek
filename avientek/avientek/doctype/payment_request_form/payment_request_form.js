// Copyright (c) 2023, Craft and contributors
// For license information, please see license.txt
{% include "erpnext/public/js/controllers/accounts.js" %}
frappe.provide("erpnext.accounts.dimensions");

frappe.ui.form.on('Payment Request Form', {
	onload: function(frm) {
        if (frm.doc.party && !frm.doc.supplier_address) {
            fetch_supplier_details(frm);
        }
		frm.set_query("issued_bank", function() {
            return {
                filters: {
                    is_company_account: 1,
                    company: frm.doc.company
                }
            };
        });
        frm.set_query("receiving_bank", function() {
            return {
                filters: {
                    is_company_account: 1,
                    company: frm.doc.company
                }
            };
        });
        frm.set_query("supplier_bank_account", function() {
            return {
                filters: {
                    is_company_account: 0,
                    party_type: frm.doc.party_type,
                    party: frm.doc.party
                }
            };
        });
		frm.set_query('party_type', function() {
            return {
                filters: {
                    name: ['in', ['Customer', 'Supplier', 'Employee']]
                }
            };
        });
		frm.fields_dict["payment_references"].grid.get_field("reference_doctype").get_query = function(doc, cdt, cdn) {
            return {
                filters: {
                    name: ['in', [
                        'Purchase Invoice',
                        'Purchase Order',
                        'Journal Entry',
                        'Expense Claim'
                    ]]
                }
            };
        };
    },
    
    refresh: function(frm) {
        if (frm.doc.docstatus === 0 ) {
            frm.add_custom_button(
                __("Purchase Order"),
                function () {
                    erpnext.utils.map_current_doc({
                        method: "avientek.events.purchase_order.create_payment_request",
                        source_doctype: "Purchase Order",
                        target: frm,
                        setters: {
                            supplier: frm.doc.party,
                            
                        },
                        get_query_filters: {
                            docstatus: 1,
                            status: ["not in", ["Closed", "On Hold"]],  
                            company: frm.doc.company
                        }
                    });
                },
                __("Get Invoices From")
            );
			frm.add_custom_button(
                __("Purchase Invoice"),
                function () {
                    erpnext.utils.map_current_doc({
                        method: "avientek.events.purchase_invoice.create_payment_request",
                        source_doctype: "Purchase Invoice",
                        target: frm,
                        setters: {
                            supplier: frm.doc.party
                        },
                        get_query_filters: {
                            docstatus: 1,
                            status: ["not in", ["Closed", "On Hold"]],  
                            company: frm.doc.company
                        }
                    });
                },
                __("Get Invoices From")
            );
			frm.add_custom_button(
                __("Expense Claim"),
                function () {
                    erpnext.utils.map_current_doc({
                        method: "avientek.events.expense_claim.create_payment_request",
                        source_doctype: "Expense Claim",
                        target: frm,
                        setters: {
                            employee: frm.doc.party
                        },
                        get_query_filters: {
                            docstatus: 1,
                            // status: ["not in", ["Closed", "On Hold"]],  
                            company: frm.doc.company
                        }
                    });
                },
                __("Get Invoices From")
            );
			// frm.add_custom_button(
            // 	__("Journal Entry"),
            // 	function () {
			// 		erpnext.utils.map_current_doc({
			// 			method: "avientek.events.journal_entry.create_payment_request",
			// 			source_doctype: "Journal Entry",
			// 			target: frm
			// 		});
            // 	},
            // 	__("Get Invoices From")
       		// );
        }
        if (frm.doc.docstatus === 1 && frm.doc.workflow_state === 'Released') {
            // Create Payment Entry button under 'Create'
            frm.add_custom_button(
                __("Payment Entry"),
                function () {
                    frappe.model.open_mapped_doc({
                        method: "avientek.avientek.doctype.payment_request_form.payment_request_form.create_payment_entry",
                        frm: frm
                    });
                },
                __("Create") // Group under 'Create'
            );

            // Create Journal Entry button under 'Create'
            frm.add_custom_button(
                __("Journal Entry"),
                function () {
                    frappe.model.open_mapped_doc({
                        method: "avientek.avientek.doctype.payment_request_form.payment_request_form.create_journal_entry",
                        frm: frm
                    });
                },
                __("Create") // Group under 'Create'
            );
        }

    },
	party: function(frm) {
		fetch_supplier_details(frm);
		if (frm.doc.party_type && frm.doc.party) {
        frappe.call({
            method: "avientek.avientek.doctype.payment_request_form.payment_request_form.fetch_party_name",
            args: {
                party_type: frm.doc.party_type,
                party: frm.doc.party
            },
            callback: function(r) {
                if (r.message) {
                    frm.set_value("party_name", r.message);
                }
            }
        });
		if (frm.doc.party_type === "Supplier" && frm.doc.party && frm.doc.company) {
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
					party: frm.doc.party,
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
	}
	},
	get_outstanding_invoice: function(frm) {
		frm.clear_table("payment_references");

		if(!frm.doc.party) {
			return;
		}

		var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
		var args = {
			"posting_date": frm.doc.posting_date,
			"company": frm.doc.company,
			"party": frm.doc.party
		}

		return  frappe.call({
			method: 'avientek.avientek.doctype.payment_request_form.payment_request_form.get_outstanding_reference_documents',
			args: {
				args:args
			},
			callback: function(r,rt) {
				if(r.message) {

					$.each(r.message, function(i, d) {
                        console.log("d",d)
						var c = frm.add_child("payment_references");
						c.reference_doctype = d.voucher_type;
						c.reference_name = d.bill_no;
						c.due_date = d.due_date
						c.total_amount = d.invoice_amount;
						c.outstanding_amount = d.outstanding;
						c.bill_no = d.bill_no;
						c.payment_amount = d.invoice_amount;
						c.invoice_date = d.posting_date;
						c.payment_term = d.payment_term;
                        c.exchange_rate = d.exchange_rate
						c.currency = d.currency;
						c.reference_attachment = d.reference_attachment;
						// c.allocated_amount = d.allocated_amount;
                        c.document_reference = d.document_reference;

					});
					frm.refresh_fields();
					frm.events.set_total_outstanding_amount(frm);
					frm.events.set_total_payment_amount(frm);
					frm.events.set_total_amount(frm);
                    frm.events.recalculate_totals(frm);

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
	set_total_payment_amount: function(frm) {
		console.log("payment_amount")
		var total_payment_amount = 0.0;
		
		$.each(frm.doc.payment_references || [], function(i, row) {
			if (row.payment_amount) {
				total_payment_amount += flt(row.payment_amount);
				
			}
		});
		console.log("payment_amount",total_payment_amount)
		frm.set_value("total_payment_amount", Math.abs(total_payment_amount));
	},
	set_total_amount: function(frm) {
		var total_amount = 0.0;
		
		$.each(frm.doc.payment_references || [], function(i, row) {
			if (row.total_amount) {
				total_amount += flt(row.total_amount);
				
			}
		});
		frm.set_value("total_amount", Math.abs(total_amount));

	},
    recalculate_totals: function(frm) {
        let total_payment = 0;
        let total_outstanding = 0;
        let total_amount = 0;

        (frm.doc.payment_references || []).forEach(row => {
            total_payment += flt(row.payment_amount);
            total_outstanding += flt(row.outstanding_amount);
            total_amount += flt(row.total_amount);
        });

        frm.set_value("total_payment_amount", total_payment);
        frm.set_value("total_outstanding_amount", total_outstanding);
        frm.set_value("total_amount", total_amount);
    },

	check_mandatory_to_fetch: function(frm) {
		$.each(["Company", "Supplier"], function(i, field) {
			if(!frm.doc[frappe.model.scrub(field)]) {
				frappe.msgprint(__("Please select {0} first", [field]));
				return false;
			}

		});
	},
    total_amount: function(frm) {
        frm.set_value("total_payment_amount", frm.doc.total_amount);

        // Step 1: Get company currency
        frappe.db.get_value('Company', frm.doc.company, 'default_currency')
        .then(({ message }) => {
            const company_currency = message.default_currency; // e.g., AED
            const issue_currency = frm.doc.issued_currency; // Issued bank currency (e.g., USD)
            const receive_currency = frm.doc.receiving_currency; // Custom field (you can fetch from child table or related doctype)

            // Step 2: Convert total_payment_amount to company currency (for total_outstanding_amount)
            return frappe.call({
                method: 'erpnext.setup.utils.get_exchange_rate',
                args: {
                    from_currency: issue_currency,
                    to_currency: company_currency,
                    posting_date: frappe.datetime.now_date(),
                    company: frm.doc.company
                }
            }).then(outstanding_rate_response => {
                const outstanding_rate = outstanding_rate_response.message || 1;
                const total_outstanding = frm.doc.total_payment_amount * outstanding_rate;
                frm.set_value("total_outstanding_amount", total_outstanding);

                // Step 3: Convert total_payment_amount to receiving currency
                return frappe.call({
                    method: 'erpnext.setup.utils.get_exchange_rate',
                    args: {
                        from_currency: issue_currency,
                        to_currency: receive_currency,
                        posting_date: frappe.datetime.now_date(),
                        company: frm.doc.company
                    }
                }).then(received_rate_response => {
                    const received_rate = received_rate_response.message || 1;
                    const total_received = frm.doc.total_payment_amount * received_rate;
                    frm.set_value("total_received_amount", total_received);

                    // Step 4: Convert total_received to company currency
                    return frappe.call({
                        method: 'erpnext.setup.utils.get_exchange_rate',
                        args: {
                            from_currency: receive_currency,
                            to_currency: company_currency,
                            posting_date: frappe.datetime.now_date(),
                            company: frm.doc.company
                        }
                    }).then(received_company_rate_response => {
                        const received_company_rate = received_company_rate_response.message || 1;
                        const total_received_company = total_received * received_company_rate;
                        frm.set_value("total_received", total_received_company);
                    });
                });
            });
        });
    },
    total_received_amount: function(frm) {
    // Step 1: Get company currency
        frappe.db.get_value('Company', frm.doc.company, 'default_currency')
        .then(({ message }) => {
            const company_currency = message.default_currency;
            const issue_currency = frm.doc.issued_currency;
            const receive_currency = frm.doc.receiving_currency;

            const total_received = frm.doc.total_received_amount;

            // Step 2: Convert received → company currency
            return frappe.call({
                method: 'erpnext.setup.utils.get_exchange_rate',
                args: {
                    from_currency: receive_currency,
                    to_currency: company_currency,
                    posting_date: frappe.datetime.now_date(),
                    company: frm.doc.company
                }
            }).then(received_company_rate_response => {
                const received_company_rate = received_company_rate_response.message || 1;
                const total_received_company = total_received * received_company_rate;
                frm.set_value("total_received", total_received_company);

                // Step 3: Convert received → issued currency (for payment amount)
                return frappe.call({
                    method: 'erpnext.setup.utils.get_exchange_rate',
                    args: {
                        from_currency: receive_currency,
                        to_currency: issue_currency,
                        posting_date: frappe.datetime.now_date(),
                        company: frm.doc.company
                    }
                }).then(payment_rate_response => {
                    let payment_rate = 1;
                    if (issue_currency === "USD" && receive_currency === "AED") {
                        payment_rate = 3.6725;
                    }
                    console.log("payment_rate", payment_rate);
                    const total_payment_amount = total_received / payment_rate;
                    frm.set_value("total_payment_amount", total_payment_amount);
                    frm.set_value("total_amount", total_payment_amount);

                    // Step 4: total_payment_amount → company currency
                    return frappe.call({
                        method: 'erpnext.setup.utils.get_exchange_rate',
                        args: {
                            from_currency: issue_currency,
                            to_currency: company_currency,
                            posting_date: frappe.datetime.now_date(),
                            company: frm.doc.company
                        }
                    }).then(outstanding_rate_response => {
                        const outstanding_rate = outstanding_rate_response.message || 1;
                        const total_outstanding = total_payment_amount * outstanding_rate;
                        frm.set_value("total_outstanding_amount", total_outstanding);
                    });
                });
            });
        });
    },
    issued_bank : function(frm) {
        if (frm.doc.issued_bank) {
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Account",
                    filters: {
                        name: frm.doc.account
                    },
                    fieldname: ["account_currency"]
                },
                callback: function(r) {
                    if (r.message) {
                        console.log("r.message.account_currency", r.message.account_currency);
                        frm.set_value("issued_currency", r.message.account_currency);
                    }
                }
            });
        }
    },
    receiving_bank : function(frm) {
        if (frm.doc.receiving_bank) {
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Account",
                    filters: {
                        name: frm.doc.receiving_account
                    },
                    fieldname: ["account_currency"]
                },
                callback: function(r) {
                    if (r.message) {
                        console.log("r.message.account_currency", r.message.account_currency);
                        frm.set_value("receiving_currency", r.message.account_currency);
                    }
                }
            });
        }
    }
});

function fetch_supplier_details(frm) {
    if (frm.doc.party_type === "Supplier") {
        frappe.call({
            method: "frappe.contacts.doctype.address.address.get_default_address",
            args: {
                doctype: frm.doc.party_type,
                name: frm.doc.party
            },
            callback: function(r) {
                if (r.message) {
                    frm.set_value("supplier_address", r.message);
                    frappe.call({
                            method: "frappe.contacts.doctype.address.address.get_address_display",
                            args: {
                                "address_dict": r.message
                            },
                            callback: function(res) {
                                if (res.message) {
                                    let clean_address = res.message.replace(/<br\s*\/?>/gi, '\n');
                                    frm.set_value("address_display", clean_address);
                                }
                            }
                        });
                }
            }
        });

        frappe.call({
            method: "avientek.avientek.doctype.payment_request_form.payment_request_form.get_supplier_bank_details",
            args: {
                supplier_name: frm.doc.party
            },
            callback: function(r) {
                if (r.message) {
                    console.log("r.message", r.message);
                    frm.set_value("supplier_bank_account", r.message.supplier_bank_account);
                    frm.set_value("account_number", r.message.bank_account_no);
                    frm.set_value("bank", r.message.bank);
                    frm.set_value("swift_code", r.message.swift_code);
                    
                }
            }
        });
    }

    frappe.call({
        method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_party_details",
        args: {
            company: frm.doc.company,
            party_type: frm.doc.party_type,
            party: frm.doc.party,
            date: frm.doc.posting_date
        },
        callback: function(r) {
            if (r.message) {
                frm.set_value("supplier_balance", r.message.party_balance); // Optionally rename to `party_balance`
            }
        }
    });
}
frappe.ui.form.on('Payment Request Reference', {
    payment_percentage: function(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    let perc = 0;

    if (row.payment_percentage) {
        perc = flt(row.payment_percentage) / 100;
    }

    if (perc > 0 && row.total_amount) {
        row.payment_amount = flt(row.total_amount) * perc;
        row.outstanding_amount = row.payment_amount * flt(row.exchange_rate || 1);
        console.log("Outstanding Amount", row.outstanding_amount)
        frm.refresh_field("payment_references");

        let total_payment = 0;
        let total_outstanding = 0;
		let total_amount = 0;
        (frm.doc.payment_references || []).forEach(r => {
            total_payment += flt(r.payment_amount);
            total_outstanding += flt(r.outstanding_amount);
			total_amount += flt(r.total_amount);
        });
		console.log("total_payment",total_payment)
		console.log("total_outstanding",total_outstanding)
		console.log("total_amount",total_amount)
        frm.set_value("total_payment_amount", total_payment);
        frm.set_value("total_outstanding_amount", total_outstanding);
		frm.set_value("total_amount", total_amount);

    }
    },
    payment_amount: function(frm, cdt, cdn) {
        frm.events.recalculate_totals(frm);
    },
    outstanding_amount: function(frm, cdt, cdn) {
        frm.events.recalculate_totals(frm);
    },
    payment_references_remove: function(frm) {
        frm.events.recalculate_totals(frm);
    }
});
