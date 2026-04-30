// Copyright (c) 2023, Craft and contributors
// For license information, please see license.txt
{% include "erpnext/public/js/controllers/accounts.js" %}
frappe.provide("erpnext.accounts.dimensions");
let is_updating_fields = false;

// ──────────────────────────────────────────────────────────────────────
// Open Purchase Order picker — pulls a Supplier's open POs into the
// Payment References child table for Advance Pay. Per Sridhar
// 2026-04-27 #3.
// ──────────────────────────────────────────────────────────────────────
function _open_po_picker(frm) {
    frappe.call({
        method: "avientek.avientek.doctype.payment_request_form.payment_request_form.get_open_purchase_orders_for_party",
        args: {
            company: frm.doc.company,
            party_type: frm.doc.party_type,
            party: frm.doc.party,
            currency: frm.doc.currency || null,
        },
        freeze: true,
        freeze_message: __("Loading open Purchase Orders…"),
        callback: function (r) {
            const rows = r.message || [];
            if (!rows.length) {
                frappe.msgprint({
                    title: __("No Open Purchase Orders"),
                    indicator: "orange",
                    message: __("No submitted, un-fully-billed Purchase Orders found for {0} in {1}{2}.", [
                        frm.doc.party,
                        frm.doc.company,
                        frm.doc.currency ? " (" + frm.doc.currency + ")" : "",
                    ]),
                });
                return;
            }
            _show_po_picker_dialog(frm, rows);
        },
    });
}

function _show_po_picker_dialog(frm, rows) {
    const fmt_money = (v, cur) => {
        const n = (parseFloat(v) || 0).toLocaleString(undefined, {
            minimumFractionDigits: 2, maximumFractionDigits: 2,
        });
        return cur ? `${cur} ${n}` : n;
    };

    const dialog_rows = rows.map(r => `
        <tr>
            <td><input type="checkbox" class="po-pick-row" data-po="${frappe.utils.escape_html(r.name)}"></td>
            <td>${frappe.utils.escape_html(r.name)}</td>
            <td>${r.transaction_date || ""}</td>
            <td class="text-right">${fmt_money(r.grand_total, r.currency)}</td>
            <td class="text-right">${fmt_money(r.pending_amt, r.currency)}</td>
            <td>${frappe.utils.escape_html(r.status || "")}</td>
        </tr>
    `).join("");

    const html = `
        <div style="max-height:50vh; overflow:auto;">
            <table class="table table-sm table-bordered" style="margin:0;">
                <thead style="position:sticky; top:0; background:#f4f5f6;">
                    <tr>
                        <th style="width:30px;"><input type="checkbox" class="po-pick-all"></th>
                        <th>PO Name</th>
                        <th>Date</th>
                        <th class="text-right">Grand Total</th>
                        <th class="text-right">Pending</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>${dialog_rows}</tbody>
            </table>
        </div>
        <div class="text-muted small" style="margin-top:6px;">
            ${__("Found {0} open Purchase Order(s) for this supplier.", [rows.length])}
        </div>
    `;

    const d = new frappe.ui.Dialog({
        title: __("Pick Open Purchase Orders"),
        size: "large",
        fields: [{ fieldtype: "HTML", fieldname: "po_grid_html" }],
        primary_action_label: __("Add Selected to Payment References"),
        primary_action() {
            const picked = [];
            d.$wrapper.find(".po-pick-row:checked").each(function () {
                picked.push($(this).attr("data-po"));
            });
            if (!picked.length) {
                frappe.show_alert({ message: __("No POs selected"), indicator: "orange" });
                return;
            }
            const by_name = Object.fromEntries(rows.map(r => [r.name, r]));
            const existing_refs = new Set(
                (frm.doc.payment_references || [])
                    .map(r => `${r.reference_doctype}|${r.reference_name}`)
            );
            let added = 0;
            for (const po_name of picked) {
                const key = `Purchase Order|${po_name}`;
                if (existing_refs.has(key)) continue;
                const r = by_name[po_name];
                const new_row = frm.add_child("payment_references");
                new_row.reference_doctype = "Purchase Order";
                new_row.reference_name = po_name;
                new_row.currency = r.currency;
                new_row.exchange_rate = r.conversion_rate || 1;
                new_row.grand_total = r.grand_total;
                new_row.base_grand_total = r.base_grand_total;
                new_row.outstanding_amount = r.pending_amt;
                new_row.invoice_date = r.transaction_date;
                added++;
            }
            frm.refresh_field("payment_references");
            frappe.show_alert({
                message: __("Added {0} Purchase Order(s) to Payment References", [added]),
                indicator: added ? "green" : "blue",
            });
            d.hide();
        },
    });
    d.fields_dict.po_grid_html.$wrapper.html(html);

    // Select-all wiring
    d.$wrapper.find(".po-pick-all").on("change", function () {
        const checked = $(this).is(":checked");
        d.$wrapper.find(".po-pick-row").prop("checked", checked);
    });

    d.show();
}

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

// ──────────────────────────────────────────────────────────────
// Combined PDF persistent progress banner
// ──────────────────────────────────────────────────────────────
// Survives tab switching / minimizing / page refresh so a long PDF
// build (for a PRF with many references) is always observable.
// State lives in localStorage under `avientek:prf:<docname>:combined_pdf_job`.
// Stale jobs (>30 min) are auto-cleared on load.
const PRF_JOB_LS_KEY = (docname) => `avientek:prf:${docname}:combined_pdf_job`;
const PRF_JOB_STALE_MS = 30 * 60 * 1000;

function prf_save_job(docname) {
    try {
        localStorage.setItem(PRF_JOB_LS_KEY(docname), JSON.stringify({
            docname: docname,
            started_at: Date.now(),
        }));
    } catch (e) {}
}

function prf_load_job(docname) {
    try {
        const raw = localStorage.getItem(PRF_JOB_LS_KEY(docname));
        if (!raw) return null;
        const job = JSON.parse(raw);
        if (!job || !job.started_at || (Date.now() - job.started_at > PRF_JOB_STALE_MS)) {
            localStorage.removeItem(PRF_JOB_LS_KEY(docname));
            return null;
        }
        return job;
    } catch (e) {
        try { localStorage.removeItem(PRF_JOB_LS_KEY(docname)); } catch (_) {}
        return null;
    }
}

function prf_clear_job(docname) {
    try { localStorage.removeItem(PRF_JOB_LS_KEY(docname)); } catch (e) {}
}

function prf_format_elapsed(ms) {
    const s = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

// Use a single dedicated DOM element per form — frm.set_intro on this
// Frappe version appends rather than replaces, so calling it on every
// tick stacked dozens of duplicate banners.
function prf_get_or_create_banner_el(frm) {
    let el = frm._prf_banner_el;
    if (el && document.body.contains(el)) return el;

    // Prefer frm.dashboard.wrapper (sits above the form body). Fall back to
    // the layout wrapper if dashboard isn't rendered yet.
    let mount = null;
    try { mount = frm.dashboard && frm.dashboard.wrapper; } catch (e) {}
    if (!mount || !mount.length) {
        try { mount = frm.layout && frm.layout.wrapper; } catch (e) {}
    }
    if (!mount || !mount.length) return null;

    el = document.createElement('div');
    el.className = 'prf-combined-pdf-banner';
    el.style.cssText = 'margin:8px 0; padding:12px 16px; background:#eaf4ff; border-left:4px solid #1f7e4f; border-radius:4px;';
    $(mount).prepend(el);
    frm._prf_banner_el = el;
    return el;
}

function prf_cancel_job(frm) {
    const docname = frm.doc.name;
    frappe.confirm(
        __('Stop the Combined PDF build for {0}? Any partial work will be discarded.', [docname]),
        function() {
            frappe.call({
                method: "avientek.avientek.doctype.payment_request_form.payment_request_form.cancel_combined_pdf",
                args: { docname: docname },
                callback: function(r) {
                    prf_clear_job(docname);
                    prf_stop_banner(frm);
                    frm._prf_last_progress = null;
                    const cancelled = r && r.message && r.message.cancelled;
                    frappe.show_alert({
                        message: cancelled
                            ? __('Combined PDF build stopped.')
                            : __('Cancel sent — worker will stop on next checkpoint.'),
                        indicator: cancelled ? 'orange' : 'blue'
                    }, 6);
                }
            });
        }
    );
}

function prf_render_banner(frm, job, progress) {
    const el = prf_get_or_create_banner_el(frm);
    if (!el) return;
    const elapsed = prf_format_elapsed(Date.now() - job.started_at);
    let pct = 0;
    let stage = __('Preparing Combined PDF…');
    let counter = '';
    if (progress && progress.total > 0) {
        pct = Math.min(100, Math.round((progress.current / progress.total) * 100));
        stage = progress.stage || stage;
        counter = ` (${progress.current}/${progress.total})`;
    }
    el.innerHTML = `
        <div style="display:flex; align-items:center; gap:12px;">
            <div style="flex:0 0 auto; color:#1f7e4f;">
                <i class="fa fa-spinner fa-spin" style="font-size:18px;"></i>
            </div>
            <div style="flex:1 1 auto; min-width:0;">
                <div style="font-weight:600; margin-bottom:4px; color:#1f3a5f;">
                    ${__('Combined PDF building')} — ${__('elapsed')} ${elapsed}
                </div>
                <div style="font-size:12px; color:#6c7680; margin-bottom:6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                    ${frappe.utils.escape_html(stage)}${counter}
                </div>
                <div style="height:6px; background:#ebeef0; border-radius:3px; overflow:hidden;">
                    <div style="height:100%; width:${pct}%; background:#1f7e4f; transition:width .3s;"></div>
                </div>
                <div style="font-size:11px; color:#8d99a6; margin-top:4px;">
                    ${__('Safe to switch tabs or refresh — this keeps running on the server.')}
                </div>
            </div>
            <div style="flex:0 0 auto;">
                <button type="button" class="btn btn-xs btn-danger prf-cancel-pdf-btn"
                    style="white-space:nowrap;">
                    ${__('Cancel')}
                </button>
            </div>
        </div>
    `;
    // Wire the cancel button fresh each render (innerHTML replaces nodes).
    const btn = el.querySelector('.prf-cancel-pdf-btn');
    if (btn) {
        btn.addEventListener('click', function(ev) {
            ev.preventDefault();
            prf_cancel_job(frm);
        });
    }
}

function prf_stop_banner(frm) {
    if (frm._prf_banner_timer) {
        clearInterval(frm._prf_banner_timer);
        frm._prf_banner_timer = null;
    }
    if (frm._prf_banner_el) {
        try { frm._prf_banner_el.remove(); } catch (e) {}
        frm._prf_banner_el = null;
    }
}

function prf_start_banner(frm) {
    const job = prf_load_job(frm.doc.name);
    if (!job) {
        prf_stop_banner(frm);
        return;
    }
    prf_render_banner(frm, job, frm._prf_last_progress);
    if (frm._prf_banner_timer) clearInterval(frm._prf_banner_timer);
    frm._prf_banner_timer = setInterval(() => {
        const j = prf_load_job(frm.doc.name);
        if (!j) {
            prf_stop_banner(frm);
            return;
        }
        prf_render_banner(frm, j, frm._prf_last_progress);
    }, 1000);
}

// Invoice drill-down link + View button styles
if (!document.getElementById('inv-drilldown-styles')) {
    $(`<style id="inv-drilldown-styles">
        .inv-ref-link {
            color: #2490EF !important;
            cursor: pointer;
            text-decoration: underline;
        }
        .inv-ref-link:hover { color: #1a6fc4 !important; }
        .inv-view-btn {
            display: inline-flex;
            align-items: center;
            gap: 3px;
            padding: 2px 8px;
            font-size: 11px;
            color: #2490EF;
            background: #f0f6ff;
            border: 1px solid #b8d4f0;
            border-radius: 4px;
            cursor: pointer;
            white-space: nowrap;
            line-height: 1.4;
        }
        .inv-view-btn:hover { background: #d6e8fc; border-color: #2490EF; }
        .inv-view-btn .view-icon { font-size: 12px; }
    </style>`).appendTo('head');
}

// Invoice attachment preview popup styles
if (!document.getElementById('inv-preview-styles')) {
    $(`<style id="inv-preview-styles">
        .inv-att-preview {
            position: fixed;
            width: 780px;
            height: 820px;
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 12px 40px rgba(0,0,0,0.22);
            z-index: 1100;
            overflow: hidden;
            border: 1px solid #d1d8dd;
            display: flex;
            flex-direction: column;
            resize: both;
            min-width: 320px;
            min-height: 250px;
        }
        .inv-att-preview.maximized {
            top: 20px !important;
            left: 20px !important;
            width: calc(100vw - 40px) !important;
            height: calc(100vh - 40px) !important;
            border-radius: 12px;
        }
        .inv-att-hdr {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 14px;
            border-bottom: 1px solid #eee;
            background: #f8f9fa;
            cursor: move;
            flex-shrink: 0;
            user-select: none;
        }
        .inv-att-hdr .inv-att-title {
            font-weight: 600;
            font-size: 13px;
            color: var(--text-color);
        }
        .inv-att-hdr .inv-att-btns {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .inv-att-hdr .inv-att-btn {
            cursor: pointer;
            font-size: 16px;
            line-height: 1;
            color: #8d99a6;
            background: none;
            border: none;
            padding: 2px 5px;
            border-radius: 4px;
        }
        .inv-att-hdr .inv-att-btn:hover { color: #36414C; background: #eee; }
        .inv-att-hdr .inv-att-close {
            cursor: pointer;
            font-size: 20px;
            line-height: 1;
            color: #8d99a6;
            background: none;
            border: none;
            padding: 0 4px;
            border-radius: 4px;
        }
        .inv-att-hdr .inv-att-close:hover { color: #e74c3c; background: #fdecea; }
        .inv-att-body {
            flex: 1;
            overflow-y: auto;
            padding: 12px;
        }
        .inv-att-body img {
            width: 100%;
            border: 1px solid #eee;
            border-radius: 4px;
            margin-bottom: 10px;
            display: block;
        }
        .inv-att-loading {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: #8d99a6;
            font-size: 13px;
            gap: 8px;
        }
        .inv-att-empty {
            padding: 40px 20px;
            text-align: center;
            color: #8d99a6;
            font-size: 13px;
        }
        .inv-att-section-title {
            font-weight: 600;
            font-size: 12px;
            color: #36414C;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 6px 0;
            margin-bottom: 8px;
            border-bottom: 2px solid #2490EF;
        }
        .inv-att-no-files {
            padding: 12px;
            text-align: center;
            color: #8d99a6;
            font-size: 12px;
            background: #f9f9f9;
            border-radius: 4px;
            margin-bottom: 8px;
        }
        .inv-att-file-link {
            display: block;
            padding: 8px 12px;
            margin-bottom: 4px;
            background: #f5f7fa;
            border-radius: 4px;
            color: #2490EF;
            text-decoration: none;
            font-size: 13px;
        }
        .inv-att-file-link:hover { background: #eef1f6; text-decoration: underline; }
    </style>`).appendTo('head');
}

frappe.ui.form.on('Payment Request Form', {
	onload: function(frm) {
        // Fetch supplier details only if party exists and details are missing
        // (fetch_supplier_details has internal checks to avoid overwriting existing data)
        if (frm.doc.party) {
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
                    name: ['in', ['Supplier', 'Employee', 'Customer']]
                }
            };
        });

        // Update Type options based on party_type
        frm.events.update_reference_type_options(frm);
    },

    refresh: function(frm) {
        // Apply debit note row styling
        frm.events.apply_debit_note_styling(frm);

        // Setup invoice drill-down links and View buttons
        frm.events.setup_invoice_drilldown(frm);

        // Re-render View buttons whenever the grid re-renders (row open/close)
        if (!frm._grid_render_bound) {
            frm._grid_render_bound = true;
            let grid = frm.fields_dict.payment_references.grid;
            if (grid) {
                let _orig_refresh = grid.refresh.bind(grid);
                grid.refresh = function() {
                    _orig_refresh();
                    setTimeout(function() { frm.events.setup_invoice_drilldown(frm); }, 250);
                };
            }
        }

        // Setup invoice attachment preview (View button click)
        frm.events.setup_invoice_attachment_preview(frm);

        // Update Type options based on party_type
        frm.events.update_reference_type_options(frm);

        // Set TR/LC document checkboxes based on TR Type (and make them read-only)
        if (frm.doc.is_tr_lc_payment) {
            frm.events.set_tr_document_checkboxes(frm);
        }

        // Render currency totals table
        frm.events.recalculate_totals(frm);

        // Render payment history for suppliers
        if (frm.doc.party_type === "Supplier" && frm.doc.party) {
            frm.events.render_payment_history(frm);
        }

        // Reset dirty state after initial load (async fetches may mark form dirty)
        if (!frm.doc.__islocal) {
            setTimeout(() => {
                frm.doc.__unsaved = 0;
                frm.page.clear_indicator();
            }, 1500);
        }

        if (frm.doc.payment_type == "Pay" && !frm.doc.__islocal) {
            // Combined PDF can take well over the 60-90 sec gateway timeout
            // for vouchers with many references. Queue it on a background
            // worker; the worker attaches the file to this PRF and emits
            // "prf_combined_pdf_ready", which we listen for below to
            // surface a "Download Now" button.
            frm.add_custom_button(__('Download Combined PDF'), function () {
                // Start persistent banner immediately so user gets live
                // feedback even if they switch tabs / minimize / refresh.
                prf_save_job(frm.doc.name);
                frm._prf_last_progress = null;
                prf_start_banner(frm);

                frappe.call({
                    method: "avientek.avientek.doctype.payment_request_form.payment_request_form.download_payment_pdf",
                    args: { docname: frm.doc.name, mode: "enqueue" },
                    callback: function(r) {
                        if (r && r.message && r.message.status === "queued") {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: 'green'
                            }, 5);
                        }
                    },
                    error: function() {
                        // Gateway rejected — don't leave the banner spinning forever.
                        prf_clear_job(frm.doc.name);
                        prf_stop_banner(frm);
                    }
                });
            });

            // Listen once per form-load for the worker's progress + ready +
            // failed events. These fire on the realtime (socket.io) channel
            // which reconnects automatically when the tab comes back, so
            // missed events on a backgrounded tab are delivered on resume.
            if (!frm._prf_combined_pdf_listener) {
                frm._prf_combined_pdf_listener = true;

                frappe.realtime.on("prf_combined_pdf_progress", function(data) {
                    if (!data || data.docname !== frm.doc.name) return;
                    frm._prf_last_progress = data;
                    const job = prf_load_job(frm.doc.name);
                    if (job) prf_render_banner(frm, job, data);
                });

                frappe.realtime.on("prf_combined_pdf_ready", function(data) {
                    if (!data || data.docname !== frm.doc.name) return;
                    prf_clear_job(frm.doc.name);
                    prf_stop_banner(frm);
                    frm._prf_last_progress = null;
                    frappe.show_alert({
                        message: __('Combined PDF ready'),
                        indicator: 'green'
                    }, 10);
                    window.open(data.file_url, "_blank");
                    frm.reload_doc();
                });

                frappe.realtime.on("prf_combined_pdf_failed", function(data) {
                    if (!data || data.docname !== frm.doc.name) return;
                    prf_clear_job(frm.doc.name);
                    prf_stop_banner(frm);
                    frm._prf_last_progress = null;
                    frappe.msgprint({
                        title: __('Combined PDF failed'),
                        message: data.error || __('Unknown error'),
                        indicator: 'red'
                    });
                });
            }

            // Rehydrate banner if a build is still in flight from a prior
            // page load (user refreshed the tab or came back after a while).
            prf_start_banner(frm);
        }

        // "Get Open Purchase Orders" button — pulls a Supplier's open POs
        // into Payment References so the user doesn't have to type each
        // PO name manually for an Advance Pay flow. Per Sridhar
        // 2026-04-27 #3. Visible only for draft Advance Pay PRFs against
        // a Supplier party.
        if (
            frm.doc.docstatus === 0
            && frm.doc.payment_type === "Advance Pay"
            && frm.doc.party_type === "Supplier"
            && frm.doc.party
        ) {
            frm.add_custom_button(__("Get Open Purchase Orders"), function () {
                _open_po_picker(frm);
            }, __("Get Items"));
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
		fetch_supplier_details(frm, true);  // force_update=true when user changes party
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

		if (frm.doc.party_type && frm.doc.party && frm.doc.company) {
			if(!frm.doc.posting_date) {
				frappe.msgprint(__("Please select Posting Date before selecting Party"))
				frm.set_value("party", "");
				return ;
			}

			// Use Avientek helper that converts party_balance to the
			// Document currency (Sridhar 2026-04-27 #10). Falls back to
			// the company-currency balance when doc.currency matches the
			// company default.
			return frappe.call({
				method: "avientek.avientek.doctype.payment_request_form.payment_request_form.get_party_balance_with_jv_inclusion",
				args: {
					company: frm.doc.company,
					party_type: frm.doc.party_type,
					party: frm.doc.party,
					target_currency: frm.doc.currency,
					posting_date: frm.doc.posting_date,
				},
				callback: function(r) {
					if (r.message != null) {
						frm.set_value("supplier_balance", r.message);
					}
				},
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
            options = ["", "Purchase Invoice", "Debit Note", "Purchase Order", "Journal Entry", "Manual"];
        } else if (frm.doc.party_type === "Employee") {
            options = ["", "Expense Claim", "Employee Advance", "Journal Entry", "Manual"];
        } else if (frm.doc.party_type === "Customer") {
            options = ["", "Credit Note", "Sales Invoice", "Payment Entry", "Journal Entry", "Manual"];
        } else {
            options = ["", "Purchase Invoice", "Debit Note", "Purchase Order", "Expense Claim", "Credit Note", "Sales Invoice", "Payment Entry", "Journal Entry", "Manual"];
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
	get_expense_claim: function(frm) {
		// Fetch both Expense Claims and Employee Advances for employees
		frm.clear_table("payment_references");

		if(!frm.doc.party) {
			return;
		}

		var args = {
			"posting_date": frm.doc.posting_date,
			"company": frm.doc.company,
			"party": frm.doc.party,
			"party_type": frm.doc.party_type,
			"reference_doctype": "Employee Documents"  // Special flag to get both
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
						c.is_return = d.is_return || 0;
						c.return_against = d.return_against || "";
					});
					frm.refresh_fields();
					frm.events.recalculate_totals(frm);
					frm.events.apply_debit_note_styling(frm);
				}
			}
		});
	},
	get_sales_invoice: function(frm) {
		frm.events._fetch_outstanding(frm, "Sales Invoice");
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

    // Map reference_doctype select values to actual Frappe DocType names
    _get_actual_doctype: function(ref_doctype) {
        const map = {
            "Purchase Invoice": "Purchase Invoice",
            "Debit Note": "Purchase Invoice",
            "Credit Note": "Sales Invoice",
            "Purchase Order": "Purchase Order",
            "Sales Invoice": "Sales Invoice",
            "Expense Claim": "Expense Claim",
            "Employee Advance": "Employee Advance",
            "Payment Entry": "Payment Entry",
            "Journal Entry": "Journal Entry",
        };
        return map[ref_doctype] || null;
    },

    // Add clickable drill-down links on invoice names and render View buttons in static cells
    setup_invoice_drilldown: function(frm) {
        function apply_drilldown() {
            let grid = frm.fields_dict.payment_references && frm.fields_dict.payment_references.grid;
            if (!grid || !grid.grid_rows) return;

            grid.grid_rows.forEach(function(row) {
                if (!row.doc || !row.doc.reference_name) return;
                if (row.doc.reference_doctype === "Manual") return;

                let $row_el = $(row.row);

                // --- Invoice drill-down link — wider selector for all Frappe v15 variants ---
                let $ref_cell = $row_el.find(
                    ".grid-static-col[data-fieldname='reference_name'], " +
                    "[data-fieldname='reference_name'] .static-area, " +
                    "[data-field='reference_name'] .static-area, " +
                    "[data-fieldname='reference_name']"
                ).first();
                if ($ref_cell.length && !$ref_cell.data("drilldown-bound")) {
                    $ref_cell.data("drilldown-bound", true);
                    $ref_cell.addClass("inv-ref-link");
                    $ref_cell.css("cursor", "pointer");
                    $ref_cell.on("click.drilldown", function(e) {
                        e.stopPropagation();
                        e.preventDefault();
                        let actual_dt = frm.events._get_actual_doctype(row.doc.reference_doctype);
                        if (actual_dt && row.doc.reference_name) {
                            frappe.set_route("Form", actual_dt, row.doc.reference_name);
                        } else {
                            frappe.msgprint(__("Cannot navigate - reference doctype or name missing"));
                        }
                    });
                }

                // --- Render View button in the view_document static cell ---
                let $view_cell = $row_el.find(
                    ".grid-static-col[data-fieldname='view_document'] .static-area, " +
                    "[data-field='view_document'] .static-area, " +
                    ".grid-static-col[data-fieldname='view_document']"
                ).first();
                if ($view_cell.length && !$view_cell.data("view-rendered")) {
                    $view_cell.data("view-rendered", true);
                    $view_cell.html('<span class="inv-view-btn" title="Preview document"><span class="view-icon">&#128065;</span> View</span>');
                    $view_cell.find(".inv-view-btn").on("click", function(e) {
                        e.stopPropagation();
                        e.preventDefault();
                        frm.events._show_view_preview(frm, row.doc.reference_doctype, row.doc.reference_name, row.doc.idx);
                    });
                }
            });
        }
        // Run multiple times to catch grid re-renders
        setTimeout(apply_drilldown, 200);
        setTimeout(apply_drilldown, 800);
        setTimeout(apply_drilldown, 2000);
    },

    // Show preview popup triggered by View button click
    _show_view_preview: function(frm, ref_doctype, ref_name, row_idx) {
        if (ref_doctype === "Manual" || !ref_name) return;
        $(frm.fields_dict.payment_references.$wrapper).trigger("view-btn-click", [ref_doctype, ref_name, row_idx]);
    },

    // Invoice attachment preview (triggered by View button click)
    setup_invoice_attachment_preview: function(frm) {
        if (frm._inv_preview_bound) return;
        frm._inv_preview_bound = true;

        let $popup = null;
        let active_key = null;
        const cache = {};

        function hide() {
            if ($popup) {
                $(document).off("mousemove.inv_drag mouseup.inv_drag");
                $popup.remove();
                $popup = null;
                active_key = null;
            }
        }

        // Listen for View button clicks (custom event from setup_invoice_drilldown)
        frm.fields_dict.payment_references.$wrapper.on(
            "view-btn-click",
            function (e, ref_doctype, ref_name, row_idx) {
                if (!ref_name || ref_doctype === "Manual") return;

                const key = ref_doctype + ":" + ref_name + ":" + (row_idx || "");
                if (key === active_key) return;

                hide();
                active_key = key;

                const $dummy = $(document.body);
                show_preview($dummy, ref_doctype, ref_name, key, row_idx);
            }
        );

        // Hide on route change
        frappe.router.on("change", hide);

        function show_preview($el, ref_doctype, ref_name, key, row_idx) {
            // Build a "Open Print View" link target. Print view shows
            // the rendered HTML directly (text-selectable), so users can
            // copy any field's value out of the document — image-based
            // attachment previews don't allow selection. Per Sridhar
            // 2026-04-27 #5: "from the documents view can we copy the
            // text from documents".
            const print_url = "/printview?doctype=" + encodeURIComponent(ref_doctype)
                + "&name=" + encodeURIComponent(ref_name)
                + "&trigger_print=0&no_letterhead=0";
            const form_url = "/app/" + encodeURIComponent(frappe.router.slug(ref_doctype))
                + "/" + encodeURIComponent(ref_name);

            $popup = $(`
                <div class="inv-att-preview">
                    <div class="inv-att-hdr">
                        <span class="inv-att-title">${frappe.utils.escape_html(ref_name)}</span>
                        <div class="inv-att-btns">
                            <a class="inv-att-btn" href="${print_url}" target="_blank" title="Open print view (text selectable, copy-friendly)">&#128424;</a>
                            <a class="inv-att-btn" href="${form_url}" target="_blank" title="Open document">&#128279;</a>
                            <button class="inv-att-btn inv-att-max" title="Maximize">&#x26F6;</button>
                            <button class="inv-att-close" title="Close">&times;</button>
                        </div>
                    </div>
                    <div class="inv-att-body">
                        <div class="inv-att-loading">
                            <span class="spinner-border spinner-border-sm"></span> Loading attachments&hellip;
                        </div>
                    </div>
                </div>
            `);

            // Position centered in viewport
            let top = Math.max(20, (window.innerHeight - 820) / 2);
            let left = Math.max(20, (window.innerWidth - 780) / 2);
            $popup.css({ top, left });

            $("body").append($popup);

            // Close only via close button (no auto-hide since it's button-triggered)
            $popup.find(".inv-att-close").on("click", hide);

            // Maximize / restore toggle
            let prev_style = null;
            $popup.find(".inv-att-max").on("click", function () {
                if ($popup.hasClass("maximized")) {
                    $popup.removeClass("maximized");
                    if (prev_style) $popup.css(prev_style);
                    $(this).html("&#x26F6;").attr("title", "Maximize");
                } else {
                    prev_style = {
                        top: $popup.css("top"),
                        left: $popup.css("left"),
                        width: $popup.css("width"),
                        height: $popup.css("height"),
                    };
                    $popup.addClass("maximized");
                    $(this).html("&#x2750;").attr("title", "Restore");
                }
            });

            // Drag by header
            let dragging = false, dx = 0, dy = 0;
            $popup.find(".inv-att-hdr").on("mousedown", function (e) {
                if ($(e.target).closest(".inv-att-btn, .inv-att-close").length) return;
                if ($popup.hasClass("maximized")) return;
                dragging = true;
                dx = e.clientX - $popup[0].offsetLeft;
                dy = e.clientY - $popup[0].offsetTop;
                e.preventDefault();
            });
            $(document).on("mousemove.inv_drag", function (e) {
                if (!dragging) return;
                $popup.css({
                    left: Math.max(0, e.clientX - dx),
                    top: Math.max(0, e.clientY - dy),
                });
            });
            $(document).on("mouseup.inv_drag", function () {
                dragging = false;
            });

            // Use cache if available
            if (cache[key]) {
                render_preview($popup, cache[key], ref_name, ref_doctype);
                return;
            }

            frappe.xcall(
                "avientek.avientek.doctype.payment_request_form.payment_request_form.get_invoice_preview_data",
                {
                    reference_doctype: ref_doctype,
                    reference_name: ref_name,
                    max_pages: 3,
                    parent_docname: frm.doc.name,
                    row_idx: row_idx || "",
                }
            ).then((data) => {
                if (!$popup) return;
                cache[key] = data || {};
                render_preview($popup, cache[key], ref_name, ref_doctype);
            }).catch(() => {
                if ($popup) {
                    $popup.find(".inv-att-body").html(
                        '<div class="inv-att-empty">Could not load preview</div>'
                    );
                }
            });
        }

        function render_preview($popup, data, ref_name, ref_doctype) {
            const $body = $popup.find(".inv-att-body");
            let html = "";
            const doc_label = ref_doctype || "Document";

            // Section 1: File attachments (uploaded PDFs/images)
            const att_images = data.attachment_images || [];
            const file_list = data.file_list || [];
            if (att_images.length) {
                html += '<div class="inv-att-section-title">Attached Documents</div>';
                for (const img of att_images) {
                    html += `<img src="${img}" loading="lazy" />`;
                }
            } else if (file_list.length) {
                // Issue 11: Render PDFs inline, images inline, Excel/other as styled badge with download icon
                html += '<div class="inv-att-section-title">Attached Documents</div>';
                for (const f of file_list) {
                    const name = (f.file_name || "").toLowerCase();
                    const url = f.file_url || "";
                    if (name.endsWith(".pdf")) {
                        html += `<iframe src="${url}#toolbar=0&navpanes=0" style="width:100%;height:800px;border:1px solid #eee;border-radius:4px;margin-bottom:10px;" loading="lazy"></iframe>`;
                    } else if (/\.(jpe?g|png|gif|webp)$/i.test(name)) {
                        html += `<img src="${url}" loading="lazy" />`;
                    } else {
                        // Excel, Word, CSV, other — show as clickable file badge
                        let icon = "📄";
                        if (/\.(xlsx?|csv)$/i.test(name)) icon = "📊";
                        else if (/\.(docx?)$/i.test(name)) icon = "📝";
                        else if (/\.(zip|rar|7z)$/i.test(name)) icon = "🗜";
                        html += `<div style="display:flex;align-items:center;gap:10px;padding:12px;border:1px solid #d6dde5;border-radius:6px;margin-bottom:8px;background:#f8f9fb;">
                            <span style="font-size:24px;">${icon}</span>
                            <div style="flex:1;">
                                <div style="font-weight:500;color:#1f2a38;">${frappe.utils.escape_html(f.file_name)}</div>
                                <div style="font-size:11px;color:#6c757d;">Click to open or download</div>
                            </div>
                            <a href="${url}" target="_blank" class="btn btn-xs btn-default">Open</a>
                        </div>`;
                    }
                }
            } else {
                html += `<div class="inv-att-no-files">No file attachments on this ${frappe.utils.escape_html(doc_label)}</div>`;
            }

            // Section 2: Print format preview
            const print_images = data.print_images || [];
            if (print_images.length) {
                html += `<div class="inv-att-section-title" style="margin-top:16px;">${frappe.utils.escape_html(doc_label)} Print Preview</div>`;
                for (const img of print_images) {
                    html += `<img src="${img}" loading="lazy" />`;
                }
            }

            // Section 3 (Issue 4): Linked Purchase Order preview
            const po_images = data.po_images || [];
            const po_name = data.po_name || "";
            if (po_images.length && po_name) {
                html += `<div class="inv-att-section-title" style="margin-top:16px;">Linked Purchase Order: ${frappe.utils.escape_html(po_name)}</div>`;
                for (const img of po_images) {
                    html += `<img src="${img}" loading="lazy" />`;
                }
            }

            // Section 4 (Issue 4): Costing Sheet attached on PRF row
            const costing_images = data.costing_images || [];
            const costing_url = data.costing_url || "";
            if (costing_images.length) {
                html += `<div class="inv-att-section-title" style="margin-top:16px;">Costing Sheet</div>`;
                for (const img of costing_images) {
                    html += `<img src="${img}" loading="lazy" />`;
                }
            } else if (costing_url) {
                html += `<div class="inv-att-section-title" style="margin-top:16px;">Costing Sheet</div>`;
                html += `<a href="${costing_url}" target="_blank" class="inv-att-file-link">Open Costing Sheet</a>`;
            }

            $body.html(html || `<div class="inv-att-empty">No data found for this ${frappe.utils.escape_html(doc_label)}</div>`);
        }
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
        let total_base_outstanding = 0; // Company currency outstanding total
        let currency_totals = {};       // Group totals by currency

        (frm.doc.payment_references || []).forEach(row => {
            // Sum amounts in company currency - include all rows (positive and negative)
            total_base_amount += flt(row.base_grand_total || 0, 2);
            total_base_outstanding += flt(row.base_outstanding_amount || 0, 2);

            // Group by billing currency
            let curr = row.currency || 'Unknown';
            if (!currency_totals[curr]) {
                currency_totals[curr] = { billing: 0, base: 0, outstanding: 0, base_outstanding: 0 };
            }
            currency_totals[curr].billing += flt(row.grand_total || 0, 2);
            currency_totals[curr].base += flt(row.base_grand_total || 0, 2);
            currency_totals[curr].outstanding += flt(row.outstanding_amount || 0, 2);
            currency_totals[curr].base_outstanding += flt(row.base_outstanding_amount || 0, 2);
        });

        // Round accumulated totals to avoid floating-point drift
        total_base_amount = flt(total_base_amount, 2);
        total_base_outstanding = flt(total_base_outstanding, 2);
        Object.keys(currency_totals).forEach(curr => {
            currency_totals[curr].billing = flt(currency_totals[curr].billing, 2);
            currency_totals[curr].base = flt(currency_totals[curr].base, 2);
            currency_totals[curr].outstanding = flt(currency_totals[curr].outstanding, 2);
            currency_totals[curr].base_outstanding = flt(currency_totals[curr].base_outstanding, 2);
        });

        // Build HTML table for currency totals
        frm.events.render_currency_totals(frm, currency_totals, total_base_amount, total_base_outstanding);

        // Only set value if it actually changed (to avoid "Not Saved" on refresh)
        if (flt(frm.doc.total_outstanding_amount, 2) !== flt(total_base_amount, 2)) {
            frappe.run_serially([
                () => frm.set_value("total_outstanding_amount", total_base_amount),
                () => { is_updating_fields = false; }
            ]);
        } else {
            is_updating_fields = false;
        }
    },

    render_currency_totals: function(frm, currency_totals, total_base_amount, total_base_outstanding) {
        // Get company currency for display
        let company_currency = frm.doc.currency || 'AED';

        let html = `<div class="currency-totals-container" style="margin: 10px 0;">
            <table class="table table-bordered table-sm" style="width: auto; min-width: 600px;">
                <thead style="background-color: #f5f5f5;">
                    <tr>
                        <th style="padding: 8px 12px;">Currency</th>
                        <th style="padding: 8px 12px; text-align: right;">Billing Amount</th>
                        <th style="padding: 8px 12px; text-align: right;">Base Amount (${company_currency})</th>
                        <th style="padding: 8px 12px; text-align: right;">Outstanding</th>
                        <th style="padding: 8px 12px; text-align: right;">Base Outstanding (${company_currency})</th>
                    </tr>
                </thead>
                <tbody>`;

        // Add row for each currency
        let currencies = Object.keys(currency_totals).sort();
        currencies.forEach(curr => {
            let data = currency_totals[curr];
            let billingFormatted = format_currency(data.billing, curr);
            let baseFormatted = format_currency(data.base, company_currency);
            let outstandingFormatted = format_currency(data.outstanding, curr);
            let baseOutstandingFormatted = format_currency(data.base_outstanding, company_currency);

            // Color negative values red
            let billingStyle = data.billing < 0 ? 'color: #e74c3c;' : '';
            let baseStyle = data.base < 0 ? 'color: #e74c3c;' : '';
            let outstandingStyle = data.outstanding < 0 ? 'color: #e74c3c;' : '';
            let baseOutstandingStyle = data.base_outstanding < 0 ? 'color: #e74c3c;' : '';

            html += `<tr>
                <td style="padding: 8px 12px; font-weight: 500;">${curr}</td>
                <td style="padding: 8px 12px; text-align: right; ${billingStyle}">${billingFormatted}</td>
                <td style="padding: 8px 12px; text-align: right; ${baseStyle}">${baseFormatted}</td>
                <td style="padding: 8px 12px; text-align: right; ${outstandingStyle}">${outstandingFormatted}</td>
                <td style="padding: 8px 12px; text-align: right; ${baseOutstandingStyle}">${baseOutstandingFormatted}</td>
            </tr>`;
        });

        // Add total row
        let totalBaseFormatted = format_currency(total_base_amount, company_currency);
        let totalBaseOutstandingFormatted = format_currency(total_base_outstanding, company_currency);
        let totalStyle = total_base_amount < 0 ? 'color: #e74c3c;' : 'color: #2e7d32;';
        let totalOutstandingStyle = total_base_outstanding < 0 ? 'color: #e74c3c;' : 'color: #2e7d32;';

        html += `</tbody>
                <tfoot style="background-color: #e8f5e9; font-weight: bold;">
                    <tr>
                        <td style="padding: 10px 12px;">TOTAL</td>
                        <td style="padding: 10px 12px; text-align: right;">-</td>
                        <td style="padding: 10px 12px; text-align: right; ${totalStyle}">${totalBaseFormatted}</td>
                        <td style="padding: 10px 12px; text-align: right;">-</td>
                        <td style="padding: 10px 12px; text-align: right; ${totalOutstandingStyle}">${totalBaseOutstandingFormatted}</td>
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

    // Check if selected Mode of Payment is TR or LC and show/hide TR/LC section
    payment_mode: function(frm) {
        if (frm.doc.payment_mode) {
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Mode of Payment",
                    filters: { name: frm.doc.payment_mode },
                    fieldname: ["custom_is_tr", "custom_is_lc"]
                },
                callback: function(r) {
                    if (r.message) {
                        let is_tr_lc = r.message.custom_is_tr || r.message.custom_is_lc;
                        frm.set_value("is_tr_lc_payment", is_tr_lc ? 1 : 0);
                    } else {
                        frm.set_value("is_tr_lc_payment", 0);
                    }
                }
            });
        } else {
            frm.set_value("is_tr_lc_payment", 0);
        }
    },

    // Auto-enable document checkboxes based on TR Type selection
    tr_type: function(frm) {
        frm.events.set_tr_document_checkboxes(frm);
    },

    // Set TR/LC document checkboxes based on TR Type
    set_tr_document_checkboxes: function(frm) {
        let tr_type = frm.doc.tr_type;

        // Reset all checkboxes first
        frm.set_value("has_proforma_invoice", 0);
        frm.set_value("has_purchase_order", 0);
        frm.set_value("has_commercial_invoice", 0);
        frm.set_value("has_bl_awb", 0);
        frm.set_value("has_delivery_note", 0);
        frm.set_value("has_bill_of_entry", 0);

        if (tr_type === "ADV") {
            // ADV: Enable Proforma Invoice and Purchase Order
            frm.set_value("has_proforma_invoice", 1);
            frm.set_value("has_purchase_order", 1);
        } else if (tr_type === "Direct") {
            // Direct: Enable Commercial Invoice, BL/AWB, Delivery Note, Bill of Entry
            frm.set_value("has_commercial_invoice", 1);
            frm.set_value("has_bl_awb", 1);
            frm.set_value("has_delivery_note", 1);
            frm.set_value("has_bill_of_entry", 1);
        }

        // Make all document checkboxes read-only (user never change)
        frm.set_df_property("has_proforma_invoice", "read_only", 1);
        frm.set_df_property("has_purchase_order", "read_only", 1);
        frm.set_df_property("has_commercial_invoice", "read_only", 1);
        frm.set_df_property("has_bl_awb", "read_only", 1);
        frm.set_df_property("has_delivery_note", "read_only", 1);
        frm.set_df_property("has_bill_of_entry", "read_only", 1);
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
    },

    // Internal Transfer: Auto-update receiving amount when issued amount changes
    issued_amount: function(frm) {
        if (frm.doc.payment_type === "Internal Transfer" && frm.doc.issued_amount) {
            frm.events.calculate_transfer_amounts(frm, 'issued');
        }
    },

    // Internal Transfer: Auto-update issued amount when receiving amount changes
    receiving_amount: function(frm) {
        if (frm.doc.payment_type === "Internal Transfer" && frm.doc.receiving_amount) {
            // Only calculate if user manually changed receiving amount (not from issued calculation)
            if (!frm._calculating_from_issued) {
                frm.events.calculate_transfer_amounts(frm, 'receiving');
            }
        }
    },

    // Calculate transfer amounts based on currency exchange rates
    calculate_transfer_amounts: function(frm, source) {
        let issued_currency = frm.doc.issued_currency;
        let receiving_currency = frm.doc.receiving_currency;

        if (!issued_currency || !receiving_currency) return;

        // If same currency, amounts are equal
        if (issued_currency === receiving_currency) {
            frm.set_value('transfer_exchange_rate', 1);
            if (source === 'issued') {
                frm._calculating_from_issued = true;
                frm.set_value('receiving_amount', frm.doc.issued_amount);
                frm._calculating_from_issued = false;
            } else {
                frm.set_value('issued_amount', frm.doc.receiving_amount);
            }
            return;
        }

        // Use existing exchange rate if set and valid (not 1 for different currencies)
        let rate = flt(frm.doc.transfer_exchange_rate);

        if (rate && rate > 0 && rate !== 1) {
            // Use existing rate for calculation
            if (source === 'issued' && frm.doc.issued_amount) {
                frm._calculating_from_issued = true;
                frm.set_value('receiving_amount', flt(frm.doc.issued_amount * rate, 2));
                frm._calculating_from_issued = false;
            } else if (source === 'receiving' && frm.doc.receiving_amount) {
                frm.set_value('issued_amount', flt(frm.doc.receiving_amount / rate, 2));
            }
        } else {
            // Fetch exchange rate
            frm.events.fetch_transfer_exchange_rate(frm, source);
        }
    },

    // Fetch exchange rate from system
    fetch_transfer_exchange_rate: function(frm, source) {
        let issued_currency = frm.doc.issued_currency;
        let receiving_currency = frm.doc.receiving_currency;

        if (!issued_currency || !receiving_currency || issued_currency === receiving_currency) return;

        frappe.call({
            method: 'erpnext.setup.utils.get_exchange_rate',
            args: {
                from_currency: issued_currency,
                to_currency: receiving_currency,
                transaction_date: frm.doc.posting_date || frappe.datetime.now_date()
            },
            callback: function(r) {
                if (r.message) {
                    let rate = flt(r.message);

                    // If rate is 1 for different currencies, it means no rate found - show message
                    if (rate === 1 && issued_currency !== receiving_currency) {
                        frappe.msgprint({
                            title: __('Exchange Rate'),
                            message: __('No exchange rate found for {0} to {1}. Please enter the rate manually.', [issued_currency, receiving_currency]),
                            indicator: 'orange'
                        });
                        frm.set_value('transfer_exchange_rate', 0);
                        return;
                    }

                    frm.set_value('transfer_exchange_rate', rate);

                    // Calculate amounts
                    if (source === 'issued' && frm.doc.issued_amount) {
                        frm._calculating_from_issued = true;
                        frm.set_value('receiving_amount', flt(frm.doc.issued_amount * rate, 2));
                        frm._calculating_from_issued = false;
                    } else if (source === 'receiving' && frm.doc.receiving_amount) {
                        frm.set_value('issued_amount', flt(frm.doc.receiving_amount / rate, 2));
                    }
                }
            }
        });
    },

    // Recalculate when exchange rate is manually changed
    transfer_exchange_rate: function(frm) {
        if (frm.doc.payment_type === "Internal Transfer" && frm.doc.transfer_exchange_rate) {
            let rate = flt(frm.doc.transfer_exchange_rate);
            if (rate > 0 && frm.doc.issued_amount) {
                frm._calculating_from_issued = true;
                frm.set_value('receiving_amount', flt(frm.doc.issued_amount * rate, 2));
                frm._calculating_from_issued = false;
            }
        }
    },

    // Recalculate when currencies change
    issued_currency: function(frm) {
        if (frm.doc.payment_type === "Internal Transfer") {
            // Reset exchange rate when currency changes
            frm.set_value('transfer_exchange_rate', 0);
            frm.set_value('receiving_amount', 0);
            if (frm.doc.issued_amount && frm.doc.receiving_currency) {
                frm.events.fetch_transfer_exchange_rate(frm, 'issued');
            }
        }
    },

    receiving_currency: function(frm) {
        if (frm.doc.payment_type === "Internal Transfer") {
            // Reset exchange rate when currency changes
            frm.set_value('transfer_exchange_rate', 0);
            frm.set_value('receiving_amount', 0);
            if (frm.doc.issued_amount && frm.doc.issued_currency) {
                frm.events.fetch_transfer_exchange_rate(frm, 'issued');
            }
        }
    }
});

// Helper to only set value if it actually changed (avoids "Not Saved" on refresh)
function set_if_changed(frm, fieldname, value) {
    if (frm.doc[fieldname] !== value) {
        frm.set_value(fieldname, value);
    }
}

function fetch_supplier_details(frm, force_update) {
    if (!frm.doc.party_type || !frm.doc.party) return;

    // Fetch address for all party types (Supplier, Employee, Customer)
    if (!frm.doc.supplier_address || force_update) {
        frappe.call({
            method: "frappe.contacts.doctype.address.address.get_default_address",
            args: {
                doctype: frm.doc.party_type,
                name: frm.doc.party
            },
            callback: function(r) {
                if (r.message) {
                    set_if_changed(frm, "supplier_address", r.message);
                    frappe.call({
                        method: "frappe.contacts.doctype.address.address.get_address_display",
                        args: {
                            "address_dict": r.message
                        },
                        callback: function(res) {
                            if (res.message) {
                                let clean_address = res.message.replace(/<br\s*\/?>/gi, '\n');
                                set_if_changed(frm, "address_display", clean_address);
                            }
                        }
                    });
                } else if (force_update) {
                    // Clear address fields if no address found
                    set_if_changed(frm, "supplier_address", "");
                    set_if_changed(frm, "address_display", "");
                }
            }
        });
    }

    // Fetch bank details for Supplier, Customer AND Employee.
    // Employee branch falls back to Employee.bank_name / bank_ac_no / iban
    // server-side when no Bank Account record exists.
    if (!frm.doc.supplier_bank_account || force_update || frm.doc.party_type === "Employee") {
        frappe.call({
            method: "avientek.avientek.doctype.payment_request_form.payment_request_form.get_supplier_bank_details",
            args: {
                supplier_name: frm.doc.party,
                party_type: frm.doc.party_type
            },
            callback: function(r) {
                if (r.message) {
                    set_if_changed(frm, "supplier_bank_account", r.message.supplier_bank_account);
                    set_if_changed(frm, "account_number", r.message.bank_account_no);
                    set_if_changed(frm, "iban", r.message.iban || "");
                    set_if_changed(frm, "bank", r.message.bank);
                    set_if_changed(frm, "swift_code", r.message.swift_code);
                }
            }
        });
    }

    // Employee-specific: pull address + contact (current_address / email /
    // cell_number) directly from the Employee master, since
    // get_default_address only returns linked Address docs and Employees
    // typically store contact info on the Employee doc itself.
    if (frm.doc.party_type === "Employee") {
        frappe.call({
            method: "avientek.avientek.doctype.payment_request_form.payment_request_form.get_employee_contact_details",
            args: { employee: frm.doc.party },
            callback: function(r) {
                if (r && r.message) {
                    if (r.message.address_display) {
                        set_if_changed(frm, "address_display", r.message.address_display);
                    }
                    if (r.message.email) {
                        set_if_changed(frm, "email", r.message.email);
                    }
                    if (r.message.telephone) {
                        set_if_changed(frm, "telephone", r.message.telephone);
                    }
                }
            }
        });
    }

    // Fetch bank letter from Supplier master
    if (frm.doc.party_type === "Supplier") {
        frappe.db.get_value('Supplier', frm.doc.party, 'avientek_bank_letter').then(r => {
            if (r.message && r.message.avientek_bank_letter) {
                set_if_changed(frm, "bank_letter", r.message.avientek_bank_letter);
            } else if (force_update) {
                set_if_changed(frm, "bank_letter", "");
            }
        });
    }

    // Fetch party balance only for new docs or when user changes party.
    // Uses Avientek helper to express the balance in the Document
    // currency (Sridhar 2026-04-27 #10).
    if (!frm.doc.supplier_balance || force_update) {
        frappe.call({
            method: "avientek.avientek.doctype.payment_request_form.payment_request_form.get_party_balance_with_jv_inclusion",
            args: {
                company: frm.doc.company,
                party_type: frm.doc.party_type,
                party: frm.doc.party,
                target_currency: frm.doc.currency,
                posting_date: frm.doc.posting_date,
            },
            callback: function(r) {
                if (r.message != null) {
                    set_if_changed(frm, "supplier_balance", r.message);
                }
            }
        });
    }
}
// Track which row/field is being updated to prevent infinite loops
let row_updating = {};

frappe.ui.form.on('Payment Request Reference', {
    view_document: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.reference_name && row.reference_doctype !== "Manual") {
            frm.events._show_view_preview(frm, row.reference_doctype, row.reference_name, row.idx);
        }
    },

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

        // Calculate outstanding from base_outstanding for all reference types
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
