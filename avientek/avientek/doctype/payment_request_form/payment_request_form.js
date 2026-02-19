// Copyright (c) 2023, Craft and contributors
// For license information, please see license.txt
{% include "erpnext/public/js/controllers/accounts.js" %}
frappe.provide("erpnext.accounts.dimensions");
let is_updating_fields = false;

// Custom CSS for debit note rows (pink/red) and manual rows (blue)
const row_styles = `
<style>
    .debit-note-row {
        background-color: #ffe6e6 !important;
    }
    .debit-note-row td {
        background-color: #ffe6e6 !important;
    }
    .debit-note-row:hover td {
        background-color: #ffcccc !important;
    }
    .manual-row {
        background-color: #e6f3ff !important;
    }
    .manual-row td {
        background-color: #e6f3ff !important;
    }
    .manual-row:hover td {
        background-color: #cce5ff !important;
    }
</style>
`;

// Inject styles once
if (!document.getElementById('payment-ref-styles')) {
    $(row_styles).attr('id', 'payment-ref-styles').appendTo('head');
}

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
        frm.set_query("party", function() {
            return {
                filters: {
                    company: frm.doc.company
                }
            };
        });
        frm.set_query("department", function() {
            return {
                filters: {
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
                    name: ['in', ['Supplier', 'Employee']]
                }
            };
        });

        // Update Type options based on party_type
        frm.events.update_reference_type_options(frm);
    },

    refresh: function(frm) {
        // Apply debit note row styling
        frm.events.apply_debit_note_styling(frm);

        // Update Type options based on party_type
        frm.events.update_reference_type_options(frm);

        // Render currency totals table
        frm.events.recalculate_totals(frm);

        // Render payment history for suppliers
        if (frm.doc.party_type === "Supplier" && frm.doc.party) {
            frm.events.render_payment_history(frm);
        }

        if (frm.doc.payment_type == "Pay" && !frm.doc.__islocal) {
            frm.add_custom_button(__('Download Combined PDF'), function () {
                window.open(
                    `/api/method/avientek.avientek.doctype.payment_request_form.payment_request_form.download_payment_pdf?docname=${encodeURIComponent(frm.doc.name)}`,
                    '_blank'
                );
            });
        }

        // "Get Invoices From" button removed - users can add rows manually
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

        // Create Payment Order button (Supplier only, any submitted state)
        if (frm.doc.docstatus === 1 && frm.doc.party_type === "Supplier") {
            frm.add_custom_button(
                __("Payment Order"),
                function () {
                    frappe.model.open_mapped_doc({
                        method: "avientek.avientek.doctype.payment_request_form.payment_request_form.make_payment_order",
                        frm: frm
                    });
                },
                __("Create")
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

        // Render payment history when party changes
        if (frm.doc.party_type === "Supplier") {
            frm.events.render_payment_history(frm);
        }

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

    party_type: function(frm) {
        // Update Type options when party_type changes
        frm.events.update_reference_type_options(frm);
    },

    // Update reference_doctype (Type) options based on party_type
    update_reference_type_options: function(frm) {
        let options = [];

        if (frm.doc.party_type === "Supplier") {
            // Supplier: Purchase Invoice, Debit Note, Purchase Order, Manual
            options = ["", "Purchase Invoice", "Debit Note", "Purchase Order", "Manual"];
        } else if (frm.doc.party_type === "Employee") {
            // Employee: Expense Claim, Manual
            options = ["", "Expense Claim", "Manual"];
        } else {
            // Default: all options (without Journal Entry)
            options = ["", "Purchase Invoice", "Debit Note", "Purchase Order", "Expense Claim", "Manual"];
        }

        // Update the options for reference_doctype field in child table
        frm.fields_dict.payment_references.grid.update_docfield_property(
            'reference_doctype',
            'options',
            options.join('\n')
        );
        frm.refresh_field('payment_references');
    },

	get_purchase_invoice: function(frm) {
		frm.events._fetch_outstanding(frm, "Purchase Invoice");
	},
	get_purchase_order: function(frm) {
		frm.events._fetch_outstanding(frm, "Purchase Order");
	},
	get_expense_claim: function(frm) {
		frm.events._fetch_outstanding(frm, "Expense Claim");
	},
	_fetch_outstanding: function(frm, reference_doctype) {
		frm.clear_table("payment_references");

		if(!frm.doc.party) {
			return;
		}

		var args = {
            "posting_date": frm.doc.posting_date,
            "company": frm.doc.company,
            "party": frm.doc.party,
            "party_type": frm.doc.party_type,
            "reference_doctype": reference_doctype
        };

		return frappe.call({
			method: 'avientek.avientek.doctype.payment_request_form.payment_request_form.get_outstanding_reference_documents',
			args: {
				args: args
			},
			callback: function(r) {
				if(r.message) {
					$.each(r.message, function(i, d) {
                        let c = frm.add_child("payment_references");
                        c.reference_doctype = d.voucher_type;
                        c.reference_name = d.voucher_no;
                        c.bill_no = d.bill_no;
                        c.due_date = d.due_date;
                        c.invoice_date = d.posting_date;
                        c.grand_total = d.grand_total;
                        c.base_grand_total = d.base_grand_total;
                        c.outstanding_amount = d.outstanding;
                        c.base_outstanding_amount = d.base_outstanding;
                        c.exchange_rate = d.exchange_rate;
                        c.currency = d.currency;
                        c.document_reference = d.document_reference;
                        // Debit note / return flags
                        c.is_return = d.is_return || 0;
                        c.return_against = d.return_against || "";
                    });
					frm.refresh_fields();
                    frm.events.recalculate_totals(frm);
                    // Apply debit note styling after refresh
                    frm.events.apply_debit_note_styling(frm);
				}
			}
		});
	},

    // Apply visual styling to rows (debit note = pink, manual = blue)
    apply_debit_note_styling: function(frm) {
        setTimeout(function() {
            let grid = frm.fields_dict.payment_references.grid;
            if (!grid || !grid.grid_rows) return;

            grid.grid_rows.forEach(function(row) {
                if (!row.doc) return;
                let $row = $(row.row);

                // Remove all custom classes first
                $row.removeClass('debit-note-row manual-row');

                // Check if this is a debit note/return row
                if (row.doc.is_return || row.doc.reference_doctype === "Debit Note" || flt(row.doc.outstanding_amount) < 0 || flt(row.doc.grand_total) < 0) {
                    $row.addClass('debit-note-row');
                }
                // Check if this is a manual row
                else if (row.doc.reference_doctype === "Manual") {
                    $row.addClass('manual-row');
                }
            });
        }, 100);
    },

    recalculate_totals: function(frm) {
        is_updating_fields = true;

        let total_base_amount = 0;      // Company currency total (always consistent)
        let currency_totals = {};       // Group totals by currency

        (frm.doc.payment_references || []).forEach(row => {
            // Sum amounts in company currency - include all rows (positive and negative)
            total_base_amount += flt(row.base_grand_total || 0);

            // Group by billing currency
            let curr = row.currency || 'Unknown';
            if (!currency_totals[curr]) {
                currency_totals[curr] = { billing: 0, base: 0 };
            }
            currency_totals[curr].billing += flt(row.grand_total || 0);
            currency_totals[curr].base += flt(row.base_grand_total || 0);
        });

        // Build HTML table for currency totals
        frm.events.render_currency_totals(frm, currency_totals, total_base_amount);

        // Only set value if it actually changed (to avoid "Not Saved" on refresh)
        if (flt(frm.doc.total_outstanding_amount) !== flt(total_base_amount)) {
            frappe.run_serially([
                () => frm.set_value("total_outstanding_amount", total_base_amount),
                () => { is_updating_fields = false; }
            ]);
        } else {
            is_updating_fields = false;
        }
    },

    render_currency_totals: function(frm, currency_totals, total_base_amount) {
        // Get company currency for display
        let company_currency = frm.doc.currency || 'AED';

        let html = `<div class="currency-totals-container" style="margin: 10px 0;">
            <table class="table table-bordered table-sm" style="width: auto; min-width: 400px;">
                <thead style="background-color: #f5f5f5;">
                    <tr>
                        <th style="padding: 8px 12px;">Currency</th>
                        <th style="padding: 8px 12px; text-align: right;">Billing Amount</th>
                        <th style="padding: 8px 12px; text-align: right;">Base Amount (${company_currency})</th>
                    </tr>
                </thead>
                <tbody>`;

        // Add row for each currency
        let currencies = Object.keys(currency_totals).sort();
        currencies.forEach(curr => {
            let data = currency_totals[curr];
            let billingFormatted = format_currency(data.billing, curr);
            let baseFormatted = format_currency(data.base, company_currency);

            // Color negative values red
            let billingStyle = data.billing < 0 ? 'color: #e74c3c;' : '';
            let baseStyle = data.base < 0 ? 'color: #e74c3c;' : '';

            html += `<tr>
                <td style="padding: 8px 12px; font-weight: 500;">${curr}</td>
                <td style="padding: 8px 12px; text-align: right; ${billingStyle}">${billingFormatted}</td>
                <td style="padding: 8px 12px; text-align: right; ${baseStyle}">${baseFormatted}</td>
            </tr>`;
        });

        // Add total row
        let totalBaseFormatted = format_currency(total_base_amount, company_currency);
        let totalStyle = total_base_amount < 0 ? 'color: #e74c3c;' : 'color: #2e7d32;';

        html += `</tbody>
                <tfoot style="background-color: #e8f5e9; font-weight: bold;">
                    <tr>
                        <td style="padding: 10px 12px;">TOTAL</td>
                        <td style="padding: 10px 12px; text-align: right;">-</td>
                        <td style="padding: 10px 12px; text-align: right; ${totalStyle}">${totalBaseFormatted}</td>
                    </tr>
                </tfoot>
            </table>
        </div>`;

        // Render to HTML field
        if (frm.fields_dict.currency_totals_html) {
            $(frm.fields_dict.currency_totals_html.wrapper).html(html);
        }
    },

    render_payment_history: function(frm) {
        // Fetch and render supplier payment history
        if (!frm.doc.party || frm.doc.party_type !== "Supplier") {
            if (frm.fields_dict.payment_history_html) {
                $(frm.fields_dict.payment_history_html.wrapper).html('');
            }
            return;
        }

        frappe.call({
            method: "avientek.avientek.doctype.payment_request_form.payment_request_form.get_supplier_payment_history",
            args: {
                supplier: frm.doc.party,
                company: frm.doc.company,
                limit: 50
            },
            callback: function(r) {
                if (r.message && r.message.length > 0) {
                    let html = frm.events.build_payment_history_table(frm, r.message);
                    if (frm.fields_dict.payment_history_html) {
                        $(frm.fields_dict.payment_history_html.wrapper).html(html);
                    }
                } else {
                    if (frm.fields_dict.payment_history_html) {
                        $(frm.fields_dict.payment_history_html.wrapper).html(
                            '<p style="color: #888; padding: 10px;">No previous payment history found for this supplier.</p>'
                        );
                    }
                }
            }
        });
    },

    build_payment_history_table: function(frm, payments) {
        let html = `
        <div class="payment-history-container" style="margin: 10px 0; overflow-x: auto;">
            <table class="table table-bordered table-sm" style="font-size: 11px; min-width: 100%;">
                <thead style="background-color: #f0f0f0;">
                    <tr>
                        <th style="padding: 6px 8px; text-align: center; width: 40px;">Sl. No.</th>
                        <th style="padding: 6px 8px;">Bank</th>
                        <th style="padding: 6px 8px; text-align: center; width: 40px;">Type</th>
                        <th style="padding: 6px 8px;">Voucher No.</th>
                        <th style="padding: 6px 8px; text-align: center; width: 80px;">Date</th>
                        <th style="padding: 6px 8px;">Beneficiary</th>
                        <th style="padding: 6px 8px;">Beneficiary IBAN/Account</th>
                        <th style="padding: 6px 8px;">Debit Account</th>
                        <th style="padding: 6px 8px; text-align: center; width: 50px;">Curr.</th>
                        <th style="padding: 6px 8px; text-align: right; width: 100px;">Amount</th>
                    </tr>
                </thead>
                <tbody>`;

        payments.forEach(function(row) {
            let dateFormatted = row.date ? frappe.datetime.str_to_user(row.date) : '';
            let amountFormatted = format_currency(row.amount, row.currency);

            html += `
                <tr>
                    <td style="padding: 5px 8px; text-align: center;">${row.sl_no}</td>
                    <td style="padding: 5px 8px;">${row.bank || ''}</td>
                    <td style="padding: 5px 8px; text-align: center;">${row.type || ''}</td>
                    <td style="padding: 5px 8px;">${row.voucher_no || ''}</td>
                    <td style="padding: 5px 8px; text-align: center;">${dateFormatted}</td>
                    <td style="padding: 5px 8px;">${row.beneficiary || ''}</td>
                    <td style="padding: 5px 8px;">${row.beneficiary_account || ''}</td>
                    <td style="padding: 5px 8px;">${row.debit_account || ''}</td>
                    <td style="padding: 5px 8px; text-align: center;">${row.currency || ''}</td>
                    <td style="padding: 5px 8px; text-align: right;">${amountFormatted}</td>
                </tr>`;
        });

        html += `
                </tbody>
            </table>
        </div>`;

        return html;
    },

	check_mandatory_to_fetch: function(frm) {
		$.each(["Company", "Supplier"], function(i, field) {
			if(!frm.doc[frappe.model.scrub(field)]) {
				frappe.msgprint(__("Please select {0} first", [field]));
				return false;
			}
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
// Track which row/field is being updated to prevent infinite loops
let row_updating = {};

frappe.ui.form.on('Payment Request Reference', {
    reference_doctype: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // For Manual type, set default exchange rate and currency
        if (row.reference_doctype === "Manual") {
            if (!row.exchange_rate) {
                row.exchange_rate = 1;
            }
            // Default to company currency if not set
            if (!row.currency && frm.doc.company) {
                frappe.db.get_value('Company', frm.doc.company, 'default_currency').then(r => {
                    if (r.message) {
                        row.currency = r.message.default_currency;
                        frm.refresh_field("payment_references");
                        frm.events.apply_debit_note_styling(frm);
                    }
                });
            }
        }
        frm.refresh_field("payment_references");
        frm.events.apply_debit_note_styling(frm);
    },

    currency: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // When currency changes, fetch exchange rate and recalculate
        if (row.currency && frm.doc.company) {
            // Store base amount before currency change (to preserve user's AED amount)
            let prev_base = flt(row.base_grand_total || 0);
            let prev_base_outstanding = flt(row.base_outstanding_amount || 0);

            frappe.db.get_value('Company', frm.doc.company, 'default_currency').then(r => {
                if (r.message) {
                    let company_currency = r.message.default_currency;
                    row._company_currency = company_currency;

                    if (row.currency === company_currency) {
                        // Same currency (AED), exchange rate = 1
                        row.exchange_rate = 1;
                        row._is_company_currency = true;

                        // Both values should be same when currency = company currency
                        if (prev_base) {
                            row.grand_total = prev_base;
                            row.base_grand_total = prev_base;
                        }
                        if (prev_base_outstanding) {
                            row.outstanding_amount = prev_base_outstanding;
                            row.base_outstanding_amount = prev_base_outstanding;
                        }

                        frm.refresh_field("payment_references");
                        frm.events.recalculate_totals(frm);
                        frm.events.apply_debit_note_styling(frm);
                    } else {
                        // Different currency (USD), fetch exchange rate
                        row._is_company_currency = false;
                        frappe.call({
                            method: 'erpnext.setup.utils.get_exchange_rate',
                            args: {
                                from_currency: row.currency,
                                to_currency: company_currency,
                                transaction_date: frm.doc.posting_date || frappe.datetime.now_date()
                            },
                            callback: function(res) {
                                if (res.message) {
                                    row.exchange_rate = flt(res.message);

                                    // Preserve base amount (AED) and calculate foreign currency equivalent
                                    if (prev_base) {
                                        row.base_grand_total = prev_base;
                                        row.grand_total = flt(prev_base / row.exchange_rate, precision('grand_total', row));
                                    }
                                    if (prev_base_outstanding) {
                                        row.base_outstanding_amount = prev_base_outstanding;
                                        row.outstanding_amount = flt(prev_base_outstanding / row.exchange_rate, precision('outstanding_amount', row));
                                    }

                                    frm.refresh_field("payment_references");
                                    frm.events.recalculate_totals(frm);
                                    frm.events.apply_debit_note_styling(frm);
                                }
                            }
                        });
                    }
                }
            });
        }
    },

    grand_total: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // Prevent infinite loops
        if (row_updating[cdn + '_grand_total']) return;
        row_updating[cdn + '_base_grand_total'] = true;

        let rate = flt(row.exchange_rate || 1);

        // Calculate base_grand_total from grand_total
        // For company currency (rate=1): both values should be same
        // For foreign currency: base = grand_total * rate
        row.base_grand_total = flt(row.grand_total * rate, precision('base_grand_total', row));

        // Also update outstanding to match
        row.outstanding_amount = row.grand_total;
        row.base_outstanding_amount = row.base_grand_total;

        frm.refresh_field("payment_references");
        frm.events.recalculate_totals(frm);
        frm.events.apply_debit_note_styling(frm);

        row_updating[cdn + '_base_grand_total'] = false;
    },

    base_grand_total: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // Prevent infinite loops
        if (row_updating[cdn + '_base_grand_total']) return;
        row_updating[cdn + '_grand_total'] = true;

        let rate = flt(row.exchange_rate || 1);

        // Only process for Manual type entries (non-Manual comes from documents)
        if (row.reference_doctype !== "Manual") {
            row_updating[cdn + '_grand_total'] = false;
            return;
        }

        // Calculate grand_total from base_grand_total
        // For company currency (rate=1): both values should be same
        // For foreign currency: grand_total = base / rate
        if (rate === 1) {
            row.grand_total = row.base_grand_total;
        } else {
            row.grand_total = flt(row.base_grand_total / rate, precision('grand_total', row));
        }

        // Also update outstanding to match
        row.outstanding_amount = row.grand_total;
        row.base_outstanding_amount = row.base_grand_total;

        frm.refresh_field("payment_references");
        frm.events.recalculate_totals(frm);
        frm.events.apply_debit_note_styling(frm);

        row_updating[cdn + '_grand_total'] = false;
    },

    outstanding_amount: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // Prevent infinite loops
        if (row_updating[cdn + '_outstanding']) return;
        row_updating[cdn + '_base_outstanding'] = true;

        let rate = flt(row.exchange_rate || 1);

        // Update base_outstanding_amount when outstanding changes
        row.base_outstanding_amount = flt(row.outstanding_amount * rate, precision('base_outstanding_amount', row));

        frm.refresh_field("payment_references");
        frm.events.recalculate_totals(frm);
        frm.events.apply_debit_note_styling(frm);

        row_updating[cdn + '_base_outstanding'] = false;
    },

    base_outstanding_amount: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // Prevent infinite loops
        if (row_updating[cdn + '_base_outstanding']) return;
        row_updating[cdn + '_outstanding'] = true;

        let rate = flt(row.exchange_rate || 1);

        // Only process for Manual type entries
        if (row.reference_doctype !== "Manual") {
            row_updating[cdn + '_outstanding'] = false;
            return;
        }

        // Calculate outstanding from base_outstanding
        if (rate === 1) {
            row.outstanding_amount = row.base_outstanding_amount;
        } else {
            row.outstanding_amount = flt(row.base_outstanding_amount / rate, precision('outstanding_amount', row));
        }

        frm.refresh_field("payment_references");
        frm.events.recalculate_totals(frm);
        frm.events.apply_debit_note_styling(frm);

        row_updating[cdn + '_outstanding'] = false;
    },

    exchange_rate: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        let rate = flt(row.exchange_rate || 1);

        // Recalculate base amounts when exchange rate changes
        if (row.reference_doctype === "Manual") {
            // For Manual: recalculate based on which currency is selected
            if (row._is_company_currency) {
                // Company currency - base is source
                if (row.base_grand_total) {
                    row.grand_total = rate === 1 ? row.base_grand_total : flt(row.base_grand_total / rate, precision('grand_total', row));
                    row.outstanding_amount = row.grand_total;
                    row.base_outstanding_amount = row.base_grand_total;
                }
            } else {
                // Foreign currency - grand_total is source
                if (row.grand_total) {
                    row.base_grand_total = flt(row.grand_total * rate, precision('base_grand_total', row));
                    row.outstanding_amount = row.grand_total;
                    row.base_outstanding_amount = row.base_grand_total;
                }
            }
        } else {
            // Non-Manual: always calculate base from billing currency
            if (row.grand_total) {
                row.base_grand_total = flt(row.grand_total * rate, precision('base_grand_total', row));
            }
            if (row.outstanding_amount) {
                row.base_outstanding_amount = flt(row.outstanding_amount * rate, precision('base_outstanding_amount', row));
            }
        }

        frm.refresh_field("payment_references");
        frm.events.recalculate_totals(frm);
    },

    payment_references_add: function(frm, cdt, cdn) {
        // Set default exchange rate for new rows
        let row = locals[cdt][cdn];
        row.exchange_rate = row.exchange_rate || 1;
        frm.refresh_field("payment_references");

        // Apply styling after a small delay to ensure row is rendered
        setTimeout(() => {
            frm.events.apply_debit_note_styling(frm);
        }, 200);
    },

    payment_references_remove: function(frm) {
        frm.events.recalculate_totals(frm);
        frm.events.apply_debit_note_styling(frm);
    }
});
