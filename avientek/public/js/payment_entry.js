// ── Client Script: "Payment Entry confirmation email" ──
frappe.ui.form.on('Payment Entry', {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button("Payment Request Form", function() {
                frappe.model.open_mapped_doc({
                    method: "avientek.events.payment_entry.create_payment_request",
                    frm: frm
                });
            }, "Create");
        }

        // Jithin 2026-05-17: reverse-direction picker. On a draft PE
        // without a PRF link, surface a "Get Payment Request Form"
        // button that opens a dialog of Released / Partially Processed
        // PRFs filtered by party (when set). Picking one fills the PE.
        if (frm.doc.docstatus === 0 && !frm.doc.payment_request_form) {
            frm.add_custom_button(__("Get Payment Request Form"), function() {
                _show_prf_picker(frm);
            }, __("Get From"));
        }

        // When a PRF IS linked, expose the back-navigation link.
        if (frm.doc.payment_request_form) {
            frm.add_custom_button(__("Open Linked PRF"), function() {
                frappe.set_route("Form", "Payment Request Form", frm.doc.payment_request_form);
            }, __("View"));
        }
    },

    setup: function(frm) {
        frm.set_query("party", function() {
            return {
                "filters": {
                    'company': frm.doc.company
                }
            };
        });
    },

    party_type: function(frm) {
        frm.set_query("party", function() {
            return {
                "filters": {
                    'company': frm.doc.company
                }
            };
        });
    },

    party: function(frm) {
        if (frm.doc.party_type && frm.doc.party) {
            let documents = {
                "Customer": "email_id",
                "Supplier": "email_id",
                "Employee": "prefered_email"
            };
            if (frm.doc.party_type != 'Shareholder') {
                frappe.db.get_value(frm.doc.party_type, frm.doc.party, documents[frm.doc.party_type])
                    .then(r => {
                        frm.set_value('contact_email', r.message[documents[frm.doc.party_type]]);
                    });
            }
        }
    }
});

// ─────────────────────────────────────────────────────────────────
// Get Payment Request Form picker (Jithin 2026-05-17)
// ─────────────────────────────────────────────────────────────────
function _show_prf_picker(frm) {
    frappe.call({
        method: "avientek.avientek.doctype.payment_request_form.payment_request_form.get_outstanding_payment_request_forms",
        args: {
            party_type: frm.doc.party_type || null,
            party: frm.doc.party || null,
            company: frm.doc.company || null,
        },
        callback: function(r) {
            const rows = (r && r.message) || [];
            if (!rows.length) {
                frappe.show_alert({
                    message: __("No Released / Partially Processed PRFs found for this party."),
                    indicator: "orange"
                }, 6);
                return;
            }

            const fields = [
                { fieldtype: "Section Break" },
                {
                    fieldtype: "HTML",
                    fieldname: "prf_picker_html",
                    options: _build_prf_picker_html(rows),
                },
            ];

            const dlg = new frappe.ui.Dialog({
                title: __("Select Payment Request Form"),
                size: "extra-large",
                fields: fields,
                primary_action_label: __("Cancel"),
                primary_action: function() { dlg.hide(); },
            });
            dlg.show();

            // Wire row clicks — using delegation on the dialog body.
            $(dlg.body).on("click", ".prf-pick-row", function() {
                const prf_name = $(this).attr("data-prf");
                if (!prf_name) return;
                dlg.hide();
                _apply_prf_to_payment_entry(frm, prf_name);
            });
        }
    });
}

function _build_prf_picker_html(rows) {
    const header = `
        <table class="table table-bordered" style="margin:0;">
            <thead style="background:#f8f9fa;">
                <tr>
                    <th>PRF</th>
                    <th>Date</th>
                    <th>Party</th>
                    <th>Payment Type</th>
                    <th class="text-right">Total</th>
                    <th class="text-right">Paid</th>
                    <th class="text-right">Outstanding</th>
                    <th>Currency</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
    `;
    const body = rows.map(function(r) {
        const fmt = function(v) {
            return format_currency(v || 0, r.currency || "");
        };
        return `
            <tr class="prf-pick-row" data-prf="${frappe.utils.escape_html(r.name)}" style="cursor:pointer;">
                <td><b>${frappe.utils.escape_html(r.name)}</b></td>
                <td>${frappe.datetime.str_to_user(r.posting_date) || ""}</td>
                <td>${frappe.utils.escape_html(r.party_name || r.party || "")}</td>
                <td>${frappe.utils.escape_html(r.payment_type || "")}</td>
                <td class="text-right">${fmt(r.total_outstanding_amount)}</td>
                <td class="text-right">${fmt(r.paid_so_far)}</td>
                <td class="text-right"><b>${fmt(r.outstanding_balance)}</b></td>
                <td>${frappe.utils.escape_html(r.currency || "")}</td>
                <td>${frappe.utils.escape_html(r.workflow_state || "")}</td>
            </tr>
        `;
    }).join("");
    const footer = `</tbody></table>
        <div class="text-muted" style="margin-top:8px; font-size:11px;">
            ${__("Click a row to populate this Payment Entry. The outstanding balance is suggested as the Paid Amount.")}
        </div>
    `;
    return header + body + footer;
}

function _apply_prf_to_payment_entry(frm, prf_name) {
    frappe.call({
        method: "frappe.client.get",
        args: { doctype: "Payment Request Form", name: prf_name },
        callback: function(r) {
            const prf = r && r.message;
            if (!prf) return;

            // Use the same Paid-amount as the remaining outstanding so
            // accountants can adjust down for a partial pay or accept
            // the suggested value for a full pay.
            frappe.call({
                method: "avientek.avientek.doctype.payment_request_form.payment_request_form.get_outstanding_payment_request_forms",
                args: {
                    party_type: prf.party_type || null,
                    party: prf.party || null,
                    company: prf.company || null,
                },
                callback: function(rr) {
                    const match = ((rr && rr.message) || []).find(x => x.name === prf_name);
                    const outstanding = match ? match.outstanding_balance : (prf.total_outstanding_amount || 0);

                    frm.set_value("payment_request_form", prf.name);
                    frm.set_value("company", prf.company);
                    if (prf.payment_type) frm.set_value("payment_type", prf.payment_type);
                    if (prf.party_type) frm.set_value("party_type", prf.party_type);
                    if (prf.party) frm.set_value("party", prf.party);
                    if (prf.payment_mode) frm.set_value("mode_of_payment", prf.payment_mode);
                    if (prf.issued_bank) frm.set_value("bank_account", prf.issued_bank);
                    if (prf.supplier_bank_account) frm.set_value("party_bank_account", prf.supplier_bank_account);
                    if (prf.account) frm.set_value("paid_from", prf.account);
                    if (prf.receiving_account) frm.set_value("paid_to", prf.receiving_account);
                    if (prf.issued_currency) frm.set_value("paid_from_account_currency", prf.issued_currency);
                    if (prf.receiving_currency) frm.set_value("paid_to_account_currency", prf.receiving_currency);
                    frm.set_value("paid_amount", outstanding);
                    frm.set_value("received_amount", outstanding);

                    frappe.show_alert({
                        message: __("PRF {0} linked. Suggested Paid Amount = {1}.", [
                            prf.name,
                            format_currency(outstanding, prf.currency || "")
                        ]),
                        indicator: "green"
                    }, 8);
                }
            });
        }
    });
}
