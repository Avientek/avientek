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

            const fields = [
                { fieldtype: "Section Break" },
                {
                    fieldtype: "HTML",
                    fieldname: "prf_picker_html",
                    options: _build_prf_picker_html(rows, frm),
                },
            ];

            const dlg = new frappe.ui.Dialog({
                title: __("Select Payment Request Form"),
                size: "extra-large",
                fields: fields,
                primary_action_label: __("Close"),
                primary_action: function() { dlg.hide(); },
            });
            dlg.show();

            // Wire row clicks (delegated).
            $(dlg.body).on("click", ".prf-pick-row", function() {
                const prf_name = $(this).attr("data-prf");
                if (!prf_name) return;
                dlg.hide();
                _apply_prf_to_payment_entry(frm, prf_name);
            });

            // Live search — filter rows by PRF / party / payment type / mode.
            $(dlg.body).on("input", ".prf-pick-search", function() {
                const q = ($(this).val() || "").toLowerCase().trim();
                let visible = 0;
                $(dlg.body).find("tbody.prf-pick-tbody tr.prf-pick-row").each(function() {
                    const text = ($(this).attr("data-search") || "").toLowerCase();
                    const show = !q || text.indexOf(q) >= 0;
                    $(this).toggle(show);
                    if (show) visible += 1;
                });
                $(dlg.body).find(".prf-pick-count").text(
                    visible + " of " + $(dlg.body).find("tbody.prf-pick-tbody tr.prf-pick-row").length
                );
                $(dlg.body).find(".prf-pick-empty-filter").toggle(visible === 0);
            });

            // Auto-focus the search box.
            setTimeout(function() {
                $(dlg.body).find(".prf-pick-search").trigger("focus");
            }, 100);
        }
    });
}

function _build_prf_picker_html(rows, frm) {
    // Filter chip strip — show party / company narrowing applied on the PE.
    const chips = [];
    if (frm.doc.party) {
        chips.push(`<span class="prf-chip">${__("Party")}: <b>${frappe.utils.escape_html(frm.doc.party)}</b></span>`);
    }
    if (frm.doc.company) {
        chips.push(`<span class="prf-chip">${__("Company")}: <b>${frappe.utils.escape_html(frm.doc.company)}</b></span>`);
    }
    const chips_html = chips.length
        ? `<div class="prf-chips">${chips.join("")}</div>`
        : `<div class="prf-chips prf-chips-empty">${__("Showing all parties — set Party on the Payment Entry to narrow this list.")}</div>`;

    // Empty-state when query returns zero rows.
    if (!rows.length) {
        return _picker_styles() + chips_html + `
            <div class="prf-empty">
                <div class="prf-empty-icon">📭</div>
                <div class="prf-empty-title">${__("No Released / Partially Processed PRFs found")}</div>
                <div class="prf-empty-hint">${__("Only PRFs that are fully approved and ready for payment appear here. Check that the PRF was Released by the Finance team.")}</div>
            </div>
        `;
    }

    const header = `
        ${_picker_styles()}
        ${chips_html}
        <div class="prf-pick-toolbar">
            <input type="text" class="form-control prf-pick-search"
                placeholder="${__("Search by PRF, party, payment type, or mode…")}" />
            <span class="prf-pick-count-wrap">
                ${__("Showing")} <span class="prf-pick-count">${rows.length} of ${rows.length}</span>
            </span>
        </div>
        <div class="prf-pick-table-wrap">
        <table class="table prf-pick-table">
            <thead>
                <tr>
                    <th>${__("PRF")}</th>
                    <th>${__("Date")}</th>
                    <th>${__("Party")}</th>
                    <th>${__("Payment Type")}</th>
                    <th>${__("Mode")}</th>
                    <th class="text-right">${__("Total")}</th>
                    <th class="text-right">${__("Paid")}</th>
                    <th class="text-right">${__("Outstanding")}</th>
                    <th>${__("Status")}</th>
                </tr>
            </thead>
            <tbody class="prf-pick-tbody">
    `;

    const body = rows.map(function(r) {
        const fmt = function(v) {
            return format_currency(v || 0, r.currency || "");
        };
        const status_cls = (r.workflow_state === "Released") ? "prf-badge-green" : "prf-badge-amber";
        const paid_cls = (r.paid_so_far || 0) > 0 ? "prf-paid-some" : "prf-paid-zero";
        const search_blob = [
            r.name, r.party, r.party_name, r.payment_type, r.payment_mode,
            r.workflow_state, r.currency, r.company,
        ].filter(Boolean).join(" ");
        return `
            <tr class="prf-pick-row" data-prf="${frappe.utils.escape_html(r.name)}"
                data-search="${frappe.utils.escape_html(search_blob)}">
                <td><b class="prf-name">${frappe.utils.escape_html(r.name)}</b></td>
                <td class="prf-date">${frappe.datetime.str_to_user(r.posting_date) || ""}</td>
                <td>${frappe.utils.escape_html(r.party_name || r.party || "")}</td>
                <td>${frappe.utils.escape_html(r.payment_type || "")}</td>
                <td class="prf-mode">${frappe.utils.escape_html(r.payment_mode || "—")}</td>
                <td class="text-right prf-amount-muted">${fmt(r.total_outstanding_amount)}</td>
                <td class="text-right ${paid_cls}">${fmt(r.paid_so_far)}</td>
                <td class="text-right prf-amount-outstanding">${fmt(r.outstanding_balance)}<div class="prf-ccy">${frappe.utils.escape_html(r.currency || "")}</div></td>
                <td><span class="prf-badge ${status_cls}">${frappe.utils.escape_html(r.workflow_state || "")}</span></td>
            </tr>
        `;
    }).join("");

    const empty_filter = `
        <tr class="prf-pick-empty-filter" style="display:none;">
            <td colspan="9" class="text-center text-muted" style="padding:24px;">
                ${__("No PRFs match your search. Try a different keyword.")}
            </td>
        </tr>
    `;

    const footer = `${empty_filter}</tbody></table></div>
        <div class="prf-pick-footer">
            <span class="prf-pick-hint">💡 ${__("Click any row to populate this Payment Entry. The Outstanding balance is suggested as the Paid Amount — adjust before submitting for partial payments.")}</span>
        </div>
    `;
    return header + body + footer;
}

function _picker_styles() {
    return `
    <style>
        .prf-chips { margin: 0 0 10px 0; display: flex; gap: 6px; flex-wrap: wrap; }
        .prf-chip { display:inline-block; padding: 3px 10px; background: #eef4ff; border: 1px solid #c8dcff; border-radius: 14px; font-size: 11px; color: #1e40af; }
        .prf-chips-empty { font-size: 11px; color: #6b7280; font-style: italic; padding: 4px 0; }

        .prf-pick-toolbar { display:flex; align-items:center; gap: 10px; margin: 0 0 10px 0; }
        .prf-pick-search { flex: 1; }
        .prf-pick-count-wrap { font-size: 12px; color: #6b7280; white-space: nowrap; }
        .prf-pick-count { font-weight: 600; color: #111; }

        .prf-pick-table-wrap { max-height: 60vh; overflow-y: auto; border: 1px solid #e5e7eb; border-radius: 6px; }
        .prf-pick-table { margin: 0; }
        .prf-pick-table thead { position: sticky; top: 0; background: #f8fafc; z-index: 1; box-shadow: 0 1px 0 #e5e7eb; }
        .prf-pick-table thead th { font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; color: #475569; font-weight: 600; padding: 10px 8px; border-bottom: 1px solid #e5e7eb; }
        .prf-pick-table tbody td { padding: 9px 8px; font-size: 12.5px; border-top: 1px solid #f0f0f0; vertical-align: middle; }

        .prf-pick-row { cursor: pointer; transition: background 0.1s; }
        .prf-pick-row:hover { background: #f5faff; }
        .prf-pick-row:active { background: #e6f2ff; }

        .prf-name { color: #1d4ed8; }
        .prf-date { color: #6b7280; font-size: 11.5px; white-space: nowrap; }
        .prf-mode { color: #475569; font-size: 11.5px; }

        .prf-amount-muted { color: #6b7280; font-size: 12px; }
        .prf-paid-zero { color: #9ca3af; font-size: 12px; }
        .prf-paid-some { color: #b45309; font-weight: 600; }
        .prf-amount-outstanding { font-weight: 700; color: #111827; font-size: 13.5px; }
        .prf-ccy { font-size: 10px; font-weight: 500; color: #6b7280; text-transform: uppercase; letter-spacing: 0.3px; margin-top: 1px; }

        .prf-badge { display: inline-block; padding: 2px 9px; font-size: 10.5px; font-weight: 600; border-radius: 12px; text-transform: uppercase; letter-spacing: 0.3px; }
        .prf-badge-green { background: #dcfce7; color: #166534; border: 1px solid #86efac; }
        .prf-badge-amber { background: #fef3c7; color: #92400e; border: 1px solid #fcd34d; }

        .prf-pick-footer { margin-top: 10px; padding: 10px 12px; background: #f9fafb; border-left: 3px solid #3b82f6; border-radius: 4px; font-size: 11.5px; color: #374151; }
        .prf-pick-hint { line-height: 1.5; }

        .prf-empty { text-align: center; padding: 40px 20px; }
        .prf-empty-icon { font-size: 48px; opacity: 0.7; margin-bottom: 8px; }
        .prf-empty-title { font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 6px; }
        .prf-empty-hint { font-size: 12px; color: #6b7280; max-width: 480px; margin: 0 auto; line-height: 1.5; }
    </style>
    `;
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
