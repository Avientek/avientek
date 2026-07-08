// ──────────────────────────────────────────────────────────────
// Quotation JS — Thin UI layer
// All authoritative calculations run server-side (before_save).
// JS only provides instant preview + handles UI events.
// ──────────────────────────────────────────────────────────────

frappe.ui.form.on('Quotation', {

    // ── Save lifecycle ──────────────────────────────────────
    before_save(frm) {
        // Server pipeline (run_calculation_pipeline) handles all calcs
    },

    after_save(frm) {
        // Reload document to sync with server-calculated values
        frm.reload_doc();
    },

    // ── Shipping mode (parent-level) ────────────────────────
    custom_shipping_mode(frm) {
        update_items_shipping_percent(frm);
    },

    // ── Customer credit / outstanding lookup (UI only) ──────
    party_name(frm) {
        if (!frm.doc.party_name) return;
        if (frm.doc.quotation_to !== 'Customer') {
            frm.set_value('custom_credit_limit', 0);
            frm.set_value('custom_outstanding', 0);
            frm.set_value('custom_overdue', 0);
            return;
        }

        let company = frm.doc.company;

        frappe.db.get_doc('Customer', frm.doc.party_name).then(customer_doc => {
            let credit_limit = 0;
            if (customer_doc.credit_limits) {
                let limit_entry = customer_doc.credit_limits.find(l => l.company === company);
                if (limit_entry) credit_limit = limit_entry.credit_limit;
            }
            frm.set_value('custom_credit_limit', credit_limit);

            if (customer_doc.payment_terms) {
                frm.set_value('custom_existing_payment_term', customer_doc.payment_terms);
            } else {
                frm.set_value('custom_existing_payment_term', '');
            }

            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'Sales Invoice',
                    filters: { customer: frm.doc.party_name, company: company, docstatus: 1 },
                    fields: ['outstanding_amount']
                },
                callback(r) {
                    let outstanding = 0;
                    (r.message || []).forEach(inv => { outstanding += flt(inv.outstanding_amount); });
                    frm.set_value('custom_outstanding', outstanding);
                }
            });

            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'Sales Order',
                    filters: { customer: frm.doc.party_name, company: company, docstatus: 1, per_billed: ["<", 100] },
                    fields: ['grand_total']
                },
                callback(r) {
                    let overdue = 0;
                    (r.message || []).forEach(so => { overdue += flt(so.grand_total); });
                    frm.set_value('custom_overdue', overdue);
                }
            });
        });
    },

    customer(frm) {
        if (!frm.doc.customer) return;
        let company = frm.doc.company;

        frappe.db.get_doc('Customer', frm.doc.customer).then(customer_doc => {
            let credit_limit = 0;
            if (customer_doc.credit_limits) {
                let limit_entry = customer_doc.credit_limits.find(l => l.company === company);
                if (limit_entry) credit_limit = limit_entry.credit_limit;
            }
            frm.set_value('credit_limit', credit_limit);

            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'Sales Invoice',
                    filters: { customer: frm.doc.customer, company: company, docstatus: 1 },
                    fields: ['outstanding_amount']
                },
                callback(r) {
                    let outstanding = 0;
                    (r.message || []).forEach(inv => { outstanding += flt(inv.outstanding_amount); });
                    frm.set_value('outstanding_credit', outstanding);
                }
            });

            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'Sales Order',
                    filters: { customer: frm.doc.customer, company: company, docstatus: 1, per_billed: ["<", 100] },
                    fields: ['grand_total']
                },
                callback(r) {
                    let overdue = 0;
                    (r.message || []).forEach(so => { overdue += flt(so.grand_total); });
                    frm.set_value('overdue', overdue);
                }
            });
        });
    },

    // ── Discount Type Selection ─────────────────────────────
    custom_discount_type(frm) {
        toggle_discount_fields(frm);
        // Mark discount as not applied when type changes
        frm._discount_applied = false;
        toggle_apply_discount_button(frm);
    },

    custom_discount_amount_value(frm) {
        // Mark discount as not applied when value changes
        frm._discount_applied = false;
        toggle_apply_discount_button(frm);
    },

    custom_discount_(frm) {
        // Mark discount as not applied when percentage changes
        frm._discount_applied = false;
        toggle_apply_discount_button(frm);
    },

    // ── Discount (already server-side) ──────────────────────
    custom_apply_discount(frm) {
        let discount_type = frm.doc.custom_discount_type || "Amount";
        let discount_amount = 0;

        if (discount_type === "Percentage") {
            // Calculate amount from percentage
            let total_selling = 0;
            (frm.doc.items || []).forEach(row => {
                total_selling += flt(row.custom_selling_price) || flt(row.amount) || 0;
            });
            if (frm.doc.custom_discount_ == null || frm.doc.custom_discount_ === "") {
                frappe.msgprint(__("Please enter discount percentage"));
                return;
            }
            discount_amount = (total_selling * flt(frm.doc.custom_discount_)) / 100;
        } else {
            // Use amount directly
            if (frm.doc.custom_discount_amount_value == null || frm.doc.custom_discount_amount_value === "") {
                frappe.msgprint(__("Please enter discount amount"));
                return;
            }
            discount_amount = flt(frm.doc.custom_discount_amount_value);
        }

        frappe.call({
            method: "avientek.events.quotation.apply_discount",
            args: {
                doc: frm.doc,
                discount_amount: discount_amount
            },
            callback(r) {
                if (r.message) {
                    frm.set_value("custom_discount_amount_value", r.message.custom_discount_amount_value);
                    frm.set_value("custom_discount_", r.message.custom_discount_);

                    (r.message.items || []).forEach(it => {
                        frappe.model.set_value("Quotation Item", it.name, "custom_special_rate", it.custom_special_rate);
                        frappe.model.set_value("Quotation Item", it.name, "custom_selling_price", it.custom_selling_price);
                        frappe.model.set_value("Quotation Item", it.name, "custom_margin_value", it.custom_margin_value);
                        frappe.model.set_value("Quotation Item", it.name, "custom_margin_", it.custom_margin_);
                        frappe.model.set_value("Quotation Item", it.name, "rate", it.custom_special_rate);
                        frappe.model.set_value("Quotation Item", it.name, "amount", it.custom_selling_price);
                        frappe.model.set_value("Quotation Item", it.name, "custom_total_", it.custom_selling_price);
                        frappe.model.set_value("Quotation Item", it.name, "custom_discount_amount_value", it.custom_discount_amount_value);
                        frappe.model.set_value("Quotation Item", it.name, "custom_discount_amount_qty", it.custom_discount_amount_qty);
                    });

                    frm.refresh_field("items");
                    frm.trigger("calculate_taxes_and_totals");

                    // Mark discount as applied and hide button
                    frm._discount_applied = true;
                    toggle_apply_discount_button(frm);

                    frappe.show_alert({message: __("Discount applied successfully"), indicator: "green"});
                }
            }
        });
    },

    // ── Incentive Type Selection ─────────────────────────────
    custom_incentive_type(frm) {
        toggle_incentive_fields(frm);
        // Mark incentive as not applied when type changes
        frm._incentive_applied = false;
        toggle_apply_incentive_button(frm);
    },

    custom_incentive_(frm) {
        if (frm.__normalizing_incentive) return;
        normalize_incentive_percent(frm, "percent");
        // Mark incentive as not applied when percentage changes
        frm._incentive_applied = false;
        toggle_apply_incentive_button(frm);
    },

    custom_incentive_amount(frm) {
        if (frm.__normalizing_incentive) return;
        normalize_incentive_percent(frm, "amount");
        // Mark incentive as not applied when amount changes
        frm._incentive_applied = false;
        toggle_apply_incentive_button(frm);
    },

    custom_apply_incentive(frm) {
        let incentive_type = frm.doc.custom_incentive_type || "Percentage";
        let incentive_amount = 0;

        // Calculate total for incentive distribution
        let total_cost = 0;
        (frm.doc.items || []).forEach(row => {
            total_cost += flt(row.custom_special_price) * (flt(row.qty) || 1);
        });

        if (incentive_type === "Percentage") {
            if (frm.doc.custom_incentive_ == null || frm.doc.custom_incentive_ === "") {
                frappe.msgprint(__("Please enter incentive percentage"));
                return;
            }
            incentive_amount = (total_cost * flt(frm.doc.custom_incentive_)) / 100;
            frm.set_value("custom_incentive_amount", incentive_amount);
        } else {
            if (frm.doc.custom_incentive_amount == null || frm.doc.custom_incentive_amount === "") {
                frappe.msgprint(__("Please enter incentive amount"));
                return;
            }
            incentive_amount = flt(frm.doc.custom_incentive_amount);
            // Calculate and set percentage
            if (total_cost > 0) {
                let percent = (incentive_amount / total_cost) * 100;
                frm.set_value("custom_incentive_", percent);
            }
        }

        // Mark incentive as applied and hide button
        frm._incentive_applied = true;
        toggle_apply_incentive_button(frm);

        // Server pipeline handles distribution on save
        frm.dirty();
        frm.save().then(() => {
            frappe.show_alert({message: __("Incentive applied successfully"), indicator: "green"});
        });
    },

    // ── Refresh / Onload ────────────────────────────────────
    refresh(frm) {
        update_custom_service_totals(frm);

        frm.set_query("selling_price_list", function () {
            return { filters: { currency: frm.doc.currency } };
        });

        // Filter customers by the selected company
        frm.set_query('party_name', function () {
            if (frm.doc.quotation_to === 'Customer' && frm.doc.company) {
                return {
                    filters: { company: frm.doc.company }
                };
            }
        });

        // Toggle discount fields based on type selection
        toggle_discount_fields(frm);
        toggle_apply_discount_button(frm);

        // Toggle incentive fields based on type selection
        toggle_incentive_fields(frm);
        toggle_apply_incentive_button(frm);

        // Hide old tables (replaced by HTML section)
        frm.set_df_property("custom_history", "hidden", 1);
        frm.set_df_property("custom_stock", "hidden", 1);
        frm.set_df_property("custom_shipment_and_margin", "hidden", 1);

        // Add click handler on items grid rows to refresh item info
        setup_items_grid_click_handler(frm);

        // Set read-only fields on Quotation Item child table
        // Fields fetched from Price List (not manually editable)
        const readonly_fields = [
            "custom_standard_price_",   // from price_list_rate
            "shipping_per",             // from Item Price (air/sea)
            "custom_finance_",          // from Item Price / Brand
            "custom_transport_",        // from Item Price (processing)
            "custom_customs_",          // from Item Price
            "std_margin_per",           // from Item Price
            // Calculated value fields
            "shipping",
            "custom_finance_value",
            "custom_transport_value",
            "reward",
            "custom_incentive_",        // controlled at parent level
            "custom_incentive_value",
            "custom_markup_value",
            "custom_cogs",
            "custom_total_",
            "custom_customs_value",
            "custom_selling_price",
            "custom_margin_",
            "custom_margin_value",
            "custom_special_rate",
            "custom_discount_amount_value",  // controlled at parent level
            "custom_discount_amount_qty",    // controlled at parent level
        ];

        readonly_fields.forEach(field => {
            frm.fields_dict.items.grid.update_docfield_property(field, "read_only", 1);
        });

        // Make parent-level total/summary fields read-only
        const readonly_parent_fields = [
            "custom_total_shipping_new",
            "custom_total_finance_new",
            "custom_total_transport_new",
            "custom_total_reward_new",
            "custom_total_incentive_new",
            "custom_total_customs_new",
            "custom_total_margin_percent_new",
            "custom_total_margin_new",
            "custom_total_buying_price",
            "custom_total_cost_new",
            "custom_total_selling_new",
        ];
        readonly_parent_fields.forEach(field => {
            frm.set_df_property(field, "read_only", 1);
        });

        // "Update Special Price" button on submitted Quotations
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Update Special Price'), function () {
                show_update_special_price_dialog(frm);
            });
        }

        // Auto-fetch Item Price defaults for rows added via the Items
        // grid's "Bulk Edit" CSV upload — see setup_bulk_upload_auto_fetch().
        setup_bulk_upload_auto_fetch(frm);
    },

    onload(frm) {
        frm.set_query('custom_quote_project', function () {
            return { query: 'avientek.events.sales_person_permission.get_project_quotation_for_user' };
        });
    },

    selling_price_list(frm) {
        if (!frm.doc.selling_price_list) return;
        // Reload defaults for all existing items in one batched call
        let rows = (frm.doc.items || []).filter(item => item.item_code);
        rows.forEach(item => { item.__defaults_fetched = true; });
        load_item_defaults_bulk(frm, rows);
    },
});


// ══════════════════════════════════════════════════════════════
// QUOTATION ITEM EVENTS
// ══════════════════════════════════════════════════════════════

frappe.ui.form.on('Quotation Item', {

    items_add(frm) {
        // no-op — server recalculates on save
    },

    items_remove(frm) {
        // no-op — server recalculates on save
    },

    // ── Item code selected ──────────────────────────────────
    item_code(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!frm.doc.party_name) {
            frappe.msgprint(__('Customer must be selected before choosing an item.'));
            return;
        }
        if (!row.item_code) return;

        // Clear previous item auxiliary data (keep for backward compatibility)
        frm.clear_table("custom_history");
        frm.clear_table("custom_stock");
        frm.clear_table("custom_shipment_and_margin");

        // Load and render item info (with table population for backward compatibility)
        refresh_item_info_html(frm, row.item_code, true);

        // Load item defaults (single server call). Mark as fetched so the
        // bulk-upload MutationObserver (setup_bulk_upload_auto_fetch) doesn't
        // redundantly re-fetch this same row if it fires before this
        // in-flight call resolves.
        row.__defaults_fetched = true;
        load_item_defaults(frm, cdt, cdn);

        // Handle service items
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
        }
    },

    // ── Price / percentage field changes → preview ──────────
    custom_special_price(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        let row = locals[cdt][cdn];
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
    },

    qty(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        let row = locals[cdt][cdn];
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
    },

    shipping_per(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        let row = locals[cdt][cdn];
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
    },

    reward_per(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
    },

    custom_incentive_(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        let row = locals[cdt][cdn];
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
    },

    custom_markup_(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        sync_shipment_margin_percent(frm, cdt, cdn);
        let row = locals[cdt][cdn];
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
    },

    custom_customs_(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        let row = locals[cdt][cdn];
        if (row.custom_customs_) {
            let final_rate = (row.custom_customs_ / 100) * row.valuation_rate;
            frappe.model.set_value(cdt, cdn, 'custom_final_valuation_rate', final_rate);
        } else {
            frappe.model.set_value(cdt, cdn, 'custom_final_valuation_rate', 0);
        }
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
    },

    custom_finance_(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
    },

    custom_transport_(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
    },

    custom_margin_(frm, cdt, cdn) {
        sync_shipment_margin_percent(frm, cdt, cdn);
    },

    // ── Shipping value → back-calc percentage ───────────────
    shipping(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        let qty = flt(row.qty) || 1;
        let standard_price = flt(row.custom_standard_price_) * qty;
        if (standard_price) {
            row.shipping_per = 100 * flt(row.shipping) / standard_price;
        }
        calculate_all_preview(frm, cdt, cdn);
    },

    // ── Reward value → back-calc percentage ─────────────────
    reward(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        let qty = flt(row.qty) || 1;
        let special_price_total = flt(row.custom_special_price) * qty;
        if (special_price_total) {
            row.reward_per = 100 * flt(row.reward) / special_price_total;
        }
        calculate_all_preview(frm, cdt, cdn);
    },

    // ── Service items ───────────────────────────────────────
    amount(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.parentfield === 'custom_service_items') {
            update_custom_service_totals(frm);
        }
    },

    custom_service_items_remove(frm) {
        update_custom_service_totals(frm);
    },

    // ── Item-level shipping mode ────────────────────────────
    custom_shipping_mode(frm, cdt, cdn) {
        const item = frappe.get_doc(cdt, cdn);
        if (!frm.doc.custom_shipment_and_margin || !frm.doc.custom_shipment_and_margin.length) return;

        const ship_row = frm.doc.custom_shipment_and_margin[0];
        let shipping_percent = 0;

        if (item.custom_shipping_mode === "Air") shipping_percent = ship_row.ship_air || 0;
        else if (item.custom_shipping_mode === "Sea") shipping_percent = ship_row.ship_sea || 0;

        frappe.model.set_value(item.doctype, item.name, "shipping_per", shipping_percent);
    },
});


// ══════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ══════════════════════════════════════════════════════════════

/**
 * Preview-only calculation — same formula as server calc_item_totals.
 * Writes directly to row properties for instant UI feedback.
 * Server recalculates authoritatively on save.
 *
 * Split into a pure compute step (no grid redraw) and a thin wrapper that
 * also redraws — bulk callers (load_item_defaults_bulk) compute for every
 * row first and redraw the grid once at the end, instead of once per row.
 */
function compute_row_preview(cdt, cdn) {
    let row = locals[cdt][cdn];

    let qty = flt(row.qty) || 1;
    let std_price = flt(row.custom_standard_price_);
    let sp = flt(row.custom_special_price);

    let shipping  = flt(row.shipping_per) * std_price / 100 * qty;
    let finance   = flt(row.custom_finance_) * sp / 100 * qty;
    let transport = flt(row.custom_transport_) * std_price / 100 * qty;
    let reward    = flt(row.reward_per) * sp / 100 * qty;

    let base_amount = (sp * qty) + shipping + finance + transport + reward;
    let incentive = flt(row.custom_incentive_) * sp * qty / 100;
    let cogs_pre = base_amount + incentive;

    let customs = flt(row.custom_customs_) * cogs_pre / 100;
    let cogs = cogs_pre + customs;
    let markup = flt(row.custom_markup_) * cogs / 100;  // markup on COGS (after customs)
    let selling_price = cogs + markup;

    let margin_value = selling_price - cogs;
    let margin_percent = selling_price ? (margin_value / selling_price) * 100 : 0;

    let per_unit_selling = selling_price / qty;

    // Write directly to row (no frappe.model.set_value to avoid cascading)
    row.shipping              = shipping;
    row.custom_finance_value  = finance;
    row.custom_transport_value = transport;
    row.reward                = reward;
    row.custom_incentive_value = incentive;
    row.custom_markup_value   = markup;
    row.custom_cogs           = cogs;
    row.custom_total_         = selling_price;
    row.custom_customs_value  = customs;
    row.custom_selling_price  = selling_price;
    row.custom_margin_        = margin_percent;
    row.custom_margin_value   = margin_value;
    row.custom_special_rate   = per_unit_selling;
    row.rate                  = per_unit_selling;
    row.amount                = selling_price;
}

function calculate_all_preview(frm, cdt, cdn) {
    compute_row_preview(cdt, cdn);
    frm.refresh_field("items");
}


/**
 * Single server call to load all item defaults when item_code is selected.
 * Replaces the old rate_calculation + update_rates nested async calls.
 */
function load_item_defaults(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    if (!row.item_code || !frm.doc.selling_price_list) return;

    frappe.call({
        method: "avientek.events.quotation.get_item_defaults",
        args: {
            item_code: row.item_code,
            price_list: frm.doc.selling_price_list,
            currency: frm.doc.currency,
            price_list_currency: frm.doc.price_list_currency,
            plc_conversion_rate: frm.doc.plc_conversion_rate || 1,
            company: frm.doc.company,
        },
        callback(r) {
            if (!r.message) return;
            apply_item_defaults_to_row(frm, cdt, cdn, r.message);
        }
    });
}


/**
 * Apply a get_item_defaults()-shaped response onto a single row via
 * frappe.model.set_value: sets price fields, fills empty percentage
 * fields (preserving user edits), and re-runs the preview calc.
 * Used by load_item_defaults() for interactive single-item selection,
 * where the field-change triggers it fires (final valuation rate,
 * shipment-margin sync) are meaningful — the item's other data (Item
 * Price popup, valuation_rate) is already loaded by that point, and
 * one row's worth of cascading redraws is imperceptible.
 *
 * NOT used for bulk application (see apply_item_defaults_to_row_silent) —
 * with 50-100 rows, firing every one of those triggers (each ending in a
 * full grid redraw) per field per row froze the browser for ~20s.
 */
function apply_item_defaults_to_row(frm, cdt, cdn, d) {
    let row = locals[cdt][cdn];

    // No Item Price for this company — show message
    if (d.no_price_for_company) {
        frappe.msgprint({
            title: __('No Item Price Found'),
            message: __('No Item Price found for <b>{0}</b> in company <b>{1}</b> and price list <b>{2}</b>. Please create an Item Price first.', [d.item_code, d.company, d.price_list]),
            indicator: 'orange'
        });
        return;
    }

    // Always set prices — special price defaults to standard price if not set
    let std_price = d.custom_standard_price_ || 0;
    let sp = d.custom_special_price || std_price;
    frappe.model.set_value(cdt, cdn, "custom_standard_price_", std_price);
    frappe.model.set_value(cdt, cdn, "custom_special_price", sp);

    // Set defaults only if field is currently empty (preserve user edits)
    if (!row.shipping_per)      frappe.model.set_value(cdt, cdn, "shipping_per", d.shipping_per_air || 0);
    if (!row.custom_transport_) frappe.model.set_value(cdt, cdn, "custom_transport_", d.custom_transport_ || 0);
    if (!row.custom_finance_)   frappe.model.set_value(cdt, cdn, "custom_finance_", d.custom_finance_ || 0);
    if (!row.std_margin_per)    frappe.model.set_value(cdt, cdn, "std_margin_per", d.std_margin_per || 0);
    if (!row.custom_customs_)   frappe.model.set_value(cdt, cdn, "custom_customs_", d.custom_customs_ || 0);
    if (!row.custom_markup_)    frappe.model.set_value(cdt, cdn, "custom_markup_", d.custom_markup_ || 0);

    // Run preview after defaults are loaded
    calculate_all_preview(frm, cdt, cdn);
}


/**
 * Bulk-safe version of apply_item_defaults_to_row: writes fields directly
 * onto the row object (bypassing frappe.model.set_value) so no field
 * triggers fire and no grid redraw happens per row. Caller computes for
 * every row, then redraws the grid exactly once at the end.
 *
 * Replicates the one field-trigger side effect that matters here
 * (custom_customs_ → custom_final_valuation_rate) inline. Skips
 * sync_shipment_margin_percent — that only affects the item-info popup's
 * shipment/margin table, which is empty for bulk-uploaded rows anyway
 * (it's populated by clicking a row, not by this fetch).
 *
 * Returns the {item_code, company, price_list} of the row if it had no
 * Item Price, so the caller can report all such rows in one message
 * instead of one msgprint per row.
 */
function apply_item_defaults_to_row_silent(cdt, cdn, d) {
    let row = locals[cdt][cdn];

    // item_name/uom are mandatory on save — fill them regardless of price
    // availability, since core's own item_code fetch never ran for this row.
    if (!row.item_name) row.item_name = d.item_name || row.item_code;
    if (!row.description) row.description = d.description || d.item_name;
    if (!row.uom && d.stock_uom) {
        row.uom = d.stock_uom;
        row.stock_uom = d.stock_uom;
        row.conversion_factor = 1;
        row.stock_qty = flt(row.qty) * 1;
    }

    if (d.no_price_for_company) {
        return { item_code: d.item_code, company: d.company, price_list: d.price_list };
    }

    let std_price = d.custom_standard_price_ || 0;
    let sp = d.custom_special_price || std_price;
    row.custom_standard_price_ = std_price;
    row.custom_special_price = sp;

    if (!row.shipping_per)      row.shipping_per = d.shipping_per_air || 0;
    if (!row.custom_transport_) row.custom_transport_ = d.custom_transport_ || 0;
    if (!row.custom_finance_)   row.custom_finance_ = d.custom_finance_ || 0;
    if (!row.std_margin_per)    row.std_margin_per = d.std_margin_per || 0;
    if (!row.custom_customs_)   row.custom_customs_ = d.custom_customs_ || 0;
    if (!row.custom_markup_)    row.custom_markup_ = d.custom_markup_ || 0;

    row.custom_final_valuation_rate = row.custom_customs_
        ? (flt(row.custom_customs_) / 100) * flt(row.valuation_rate)
        : 0;

    compute_row_preview(cdt, cdn);
    return null;
}


/**
 * Batched version of load_item_defaults() — one request for many rows.
 * Used for bulk-uploaded rows so a 50-100 row CSV import doesn't fire
 * that many separate requests, and applies results silently (see
 * apply_item_defaults_to_row_silent), redrawing the grid exactly once
 * at the end instead of hundreds of times.
 */
function load_item_defaults_bulk(frm, rows) {
    if (!rows.length || !frm.doc.selling_price_list) return;

    let item_codes = [...new Set(rows.map(r => r.item_code))];

    frappe.call({
        method: "avientek.events.quotation.get_item_defaults_bulk",
        args: {
            item_codes: item_codes,
            price_list: frm.doc.selling_price_list,
            currency: frm.doc.currency,
            price_list_currency: frm.doc.price_list_currency,
            plc_conversion_rate: frm.doc.plc_conversion_rate || 1,
            company: frm.doc.company,
        },
        callback(r) {
            if (!r.message) return;
            let results = r.message;
            let missing_price = [];

            rows.forEach(row => {
                let d = results[row.item_code];
                if (!d) return;
                let missing = apply_item_defaults_to_row_silent(row.doctype, row.name, d);
                if (missing) missing_price.push(missing.item_code);
            });

            frm.dirty();
            frm.refresh_field("items");

            frappe.show_alert({
                message: __('Prices fetched for {0} item(s).', [rows.length - missing_price.length]),
                indicator: 'green'
            });

            if (missing_price.length) {
                frappe.msgprint({
                    title: __('No Item Price Found'),
                    message: __('No Item Price found for: {0}', [missing_price.join(', ')]),
                    indicator: 'orange'
                });
            }
        }
    });
}


/**
 * Auto-fetch Item Price defaults for rows added via the Items grid's
 * "Bulk Edit" CSV upload (Download/Upload buttons on the grid). That core
 * Frappe feature writes item_code (and other columns) directly onto new
 * child rows and never fires the item_code field trigger — so the normal
 * load_item_defaults() call in the item_code handler above never runs for
 * those rows.
 *
 * Rather than patching Frappe's core Grid class (which runs during every
 * grid's construction and previously caused the whole form to fail to
 * render when it broke), this watches the Items grid's DOM with a
 * MutationObserver and reacts only after rows have already been painted —
 * it can't interfere with initial form layout since it only ever runs
 * after the form already exists. All pending rows are fetched in a single
 * batched call (load_item_defaults_bulk) so a 50-row upload fills in at
 * once instead of trickling in via 50 separate requests.
 */
function setup_bulk_upload_auto_fetch(frm) {
    if (frm.__bulk_upload_observer) return;  // set up once per form instance

    let grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    let wrapper = grid && grid.wrapper && grid.wrapper.get(0);
    if (!wrapper) return;

    let debounce_timer = null;
    let observer = new MutationObserver(() => {
        clearTimeout(debounce_timer);
        debounce_timer = setTimeout(() => {
            let pending = (frm.doc.items || []).filter(
                item => item.item_code && !flt(item.custom_standard_price_) && !item.__defaults_fetched
            );
            if (!pending.length) return;

            pending.forEach(item => { item.__defaults_fetched = true; });
            frappe.show_alert({
                message: __('Fetching item prices for {0} row(s)...', [pending.length]),
                indicator: 'blue'
            });
            load_item_defaults_bulk(frm, pending);
        }, 300);
    });

    observer.observe(wrapper, { childList: true, subtree: true });
    frm.__bulk_upload_observer = observer;
}


/**
 * Normalize incentive percent ↔ amount on the parent Quotation.
 * BUG FIX: custom_cogs already includes qty, so do NOT multiply by qty again.
 */
function normalize_incentive_percent(frm, source) {
    if (frm.__normalizing_incentive) return;
    frm.__normalizing_incentive = true;

    let total_cost = 0;
    frm.doc.items.forEach(row => {
        total_cost += flt(row.custom_special_price) * (flt(row.qty) || 1);  // sp * qty
    });

    if (!total_cost) {
        frm.__normalizing_incentive = false;
        return;
    }

    if (!flt(frm.doc.custom_incentive_) && !flt(frm.doc.custom_incentive_amount)) {
        frm.set_value("custom_incentive_", 0);
        frm.set_value("custom_incentive_amount", 0);
        frm.__normalizing_incentive = false;
        return;
    }

    if (source === "percent") {
        let amount = (total_cost * flt(frm.doc.custom_incentive_)) / 100;
        frm.set_value("custom_incentive_amount", amount);
    }

    if (source === "amount") {
        let percent = (flt(frm.doc.custom_incentive_amount) / total_cost) * 100;
        frm.set_value("custom_incentive_", percent);
    }

    frm.__normalizing_incentive = false;
}


// ── Service items helpers (unchanged) ───────────────────────

function handle_qty_or_rate_change(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    if (row.parentfield === 'custom_service_items') {
        calculate_custom_amount(frm, row);
        frm.refresh_field('custom_service_items');
    }
}

function calculate_custom_amount(frm, row) {
    row.amount = flt(row.qty) * flt(row.rate);
}

function update_custom_service_totals(frm) {
    let total_qty = 0;
    let total_amount = 0;

    (frm.doc.custom_service_items || []).forEach(row => {
        total_qty += flt(row.qty);
        total_amount += flt(row.amount);
    });

    frm.set_value('custom_total_qty', total_qty);
    frm.set_value('custom_total', total_amount);

    let conversion_rate = flt(frm.doc.conversion_rate || 1);
    frm.set_value('custom_total_company_currency', total_amount * conversion_rate);
}


// ── Shipment / margin sync helpers (unchanged) ──────────────

function sync_shipment_margin_percent(frm, cdt, cdn) {
    let item_row = locals[cdt][cdn];
    if (!item_row || item_row.custom_margin_ == null) return;
    if (!frm.doc.custom_shipment_and_margin || !frm.doc.custom_shipment_and_margin.length) return;

    let ship_row = frm.doc.custom_shipment_and_margin[0];
    frappe.model.set_value(ship_row.doctype, ship_row.name, "margin", item_row.custom_margin_);
}

function update_items_shipping_percent(frm) {
    if (!frm.doc.items || !frm.doc.items.length) return;
    if (!frm.doc.custom_shipment_and_margin || !frm.doc.custom_shipment_and_margin.length) return;

    const ship_row = frm.doc.custom_shipment_and_margin[0];
    const mode = frm.doc.custom_shipping_mode;
    let shipping_percent = 0;

    if (mode === "Air") shipping_percent = ship_row.ship_air || 0;
    else if (mode === "Sea") shipping_percent = ship_row.ship_sea || 0;

    frm.doc.items.forEach(item => {
        frappe.model.set_value(item.doctype, item.name, "shipping_per", shipping_percent);
    });
}


// ── Discount field visibility helpers ────────────────────────

/**
 * Toggle visibility of discount fields based on discount type selection.
 * Shows either Amount field or Percentage field, hides the other.
 */
function toggle_discount_fields(frm) {
    let discount_type = frm.doc.custom_discount_type || "Amount";

    if (discount_type === "Percentage") {
        // Show percentage, hide amount (make amount read-only to show calculated value)
        frm.set_df_property("custom_discount_", "hidden", 0);
        frm.set_df_property("custom_discount_", "read_only", 0);
        frm.set_df_property("custom_discount_amount_value", "hidden", 0);
        frm.set_df_property("custom_discount_amount_value", "read_only", 1);  // Shows calculated amount
    } else {
        // Show amount, hide percentage (make percentage read-only to show calculated value)
        frm.set_df_property("custom_discount_amount_value", "hidden", 0);
        frm.set_df_property("custom_discount_amount_value", "read_only", 0);
        frm.set_df_property("custom_discount_", "hidden", 0);
        frm.set_df_property("custom_discount_", "read_only", 1);  // Shows calculated percentage
    }
}

/**
 * Toggle Apply Discount button visibility.
 * Hide if discount has been applied and values haven't changed.
 */
function toggle_apply_discount_button(frm) {
    let has_discount_value = flt(frm.doc.custom_discount_amount_value) > 0 || flt(frm.doc.custom_discount_) > 0;
    let discount_applied = frm._discount_applied || false;

    // Show button if there's a value to apply and discount hasn't been applied yet
    if (has_discount_value && !discount_applied) {
        frm.set_df_property("custom_apply_discount", "hidden", 0);
    } else if (discount_applied) {
        // Hide button after discount is applied
        frm.set_df_property("custom_apply_discount", "hidden", 1);
    } else {
        // No value entered yet, show button but it will show error on click
        frm.set_df_property("custom_apply_discount", "hidden", 0);
    }
}


// ── Incentive field visibility helpers ────────────────────────

/**
 * Toggle visibility of incentive fields based on incentive type selection.
 * Shows either Amount field or Percentage field, hides the other.
 */
function toggle_incentive_fields(frm) {
    let incentive_type = frm.doc.custom_incentive_type || "Percentage";

    if (incentive_type === "Percentage") {
        // Show percentage as editable, amount as read-only (shows calculated value)
        frm.set_df_property("custom_incentive_", "hidden", 0);
        frm.set_df_property("custom_incentive_", "read_only", 0);
        frm.set_df_property("custom_incentive_amount", "hidden", 0);
        frm.set_df_property("custom_incentive_amount", "read_only", 1);
    } else {
        // Show amount as editable, percentage as read-only (shows calculated value)
        frm.set_df_property("custom_incentive_amount", "hidden", 0);
        frm.set_df_property("custom_incentive_amount", "read_only", 0);
        frm.set_df_property("custom_incentive_", "hidden", 0);
        frm.set_df_property("custom_incentive_", "read_only", 1);
    }
}

/**
 * Toggle Apply Incentive button visibility.
 * Hide if incentive has been applied and values haven't changed.
 */
function toggle_apply_incentive_button(frm) {
    let has_incentive_value = flt(frm.doc.custom_incentive_amount) > 0 || flt(frm.doc.custom_incentive_) > 0;
    let incentive_applied = frm._incentive_applied || false;

    // Show button if there's a value to apply and incentive hasn't been applied yet
    if (has_incentive_value && !incentive_applied) {
        frm.set_df_property("custom_apply_incentive", "hidden", 0);
    } else if (incentive_applied) {
        // Hide button after incentive is applied
        frm.set_df_property("custom_apply_incentive", "hidden", 1);
    } else {
        // No value entered yet, show button but it will show error on click
        frm.set_df_property("custom_apply_incentive", "hidden", 0);
    }
}


// ── Item Info HTML Renderer ───────────────────────────────────

/**
 * Render item information (stock, history, shipment/margin) as HTML.
 * Uses Frappe's row/col classes for proper responsive columns.
 */
function render_item_info_html(data, item_code) {
    // Stock section - table with header
    let stockHtml = '';
    if (data.stock && data.stock.length > 0) {
        stockHtml = `
            <table class="table table-sm table-borderless" style="margin: 0; font-size: 12px;">
                <thead>
                    <tr style="color: #888; font-size: 11px; border-bottom: 1px solid #dee2e6;">
                        <th style="font-weight: 600;">Company</th>
                        <th style="text-align: right; font-weight: 600;">Available</th>
                        <th style="text-align: right; font-weight: 600;">Free</th>
                        <th style="text-align: right; font-weight: 600;">Projected</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.stock.map(s => {
                        let freeColor = s.free_stock > 0 ? '#28a745' : '#dc3545';
                        let freeBg = s.free_stock > 0 ? '#d4edda' : '#f8d7da';
                        let projColor = s.projected_stock > 0 ? '#28a745' : '#dc3545';
                        let projBg = s.projected_stock > 0 ? '#d4edda' : '#f8d7da';
                        return `
                            <tr>
                                <td>${s.company}</td>
                                <td style="text-align: right;">${s.actual_stock}</td>
                                <td style="text-align: right;">
                                    <span style="background:${freeBg}; color:${freeColor}; padding: 2px 8px; border-radius: 4px; font-weight: bold;">
                                        ${s.free_stock}
                                    </span>
                                </td>
                                <td style="text-align: right;">
                                    <span style="background:${projBg}; color:${projColor}; padding: 2px 8px; border-radius: 4px; font-weight: bold;">
                                        ${s.projected_stock}
                                    </span>
                                </td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        `;
    } else {
        stockHtml = '<span class="text-muted">No stock data available</span>';
    }

    // History section
    let historyHtml = '';
    if (data.history && data.history.length > 0) {
        historyHtml = `
            <table class="table table-sm table-borderless" style="margin: 0; font-size: 12px;">
                <tbody>
                    ${data.history.map(h => {
                        let badge = h.doctype === 'Sales Invoice'
                            ? '<span class="badge" style="background:#28a745;color:#fff;">INV</span>'
                            : (h.doctype === 'Sales Order'
                                ? '<span class="badge" style="background:#007bff;color:#fff;">SO</span>'
                                : '<span class="badge" style="background:#6c757d;color:#fff;">QN</span>');
                        return `
                            <tr>
                                <td style="width:50px;">${badge}</td>
                                <td><a href="/app/${h.doctype.toLowerCase().replace(/ /g, '-')}/${h.name}" target="_blank">${h.name}</a></td>
                                <td style="text-align:right;"><strong>${h.qty}</strong> pcs</td>
                                <td style="text-align:right;"><strong>${format_currency(h.rate)}</strong></td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        `;
    } else {
        historyHtml = '<span class="text-muted">No previous transactions</span>';
    }

    // Shipping & Margin section
    let shippingHtml = '';
    if (data.shipment_margin) {
        let sm = data.shipment_margin;
        let cal_margin = flt(data.cal_margin || 0).toFixed(2);
        let std_margin = flt(sm.std_margin || 0);
        shippingHtml = `
            <table class="table table-sm table-borderless" style="margin: 0; font-size: 12px; text-align: center;">
                <thead>
                    <tr style="color: #888; font-size: 11px; border-bottom: 1px solid #dee2e6;">
                        <th style="font-weight: 600;">AIR</th>
                        <th style="font-weight: 600;">SEA</th>
                        <th style="font-weight: 600; color: #28a745;">St.Margin</th>
                        <th style="font-weight: 600; color: #dc3545;">Cl.Margin</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="font-size: 16px; font-weight: bold;">${sm.ship_air || 0}%</td>
                        <td style="font-size: 16px; font-weight: bold;">${sm.ship_sea || 0}%</td>
                        <td style="font-size: 16px; font-weight: bold; color: #28a745;">${std_margin}%</td>
                        <td style="font-size: 16px; font-weight: bold; color: #dc3545;">${cal_margin}%</td>
                    </tr>
                </tbody>
            </table>
        `;
    } else {
        shippingHtml = '<span class="text-muted">No data</span>';
    }

    // Combine into 3-column layout
    let html = `
        <div class="row" style="margin: 0 0 15px 0; padding: 10px; background: #f8f9fa; border-radius: 8px;">
            <div class="col-md-4">
                <div style="font-weight: 600; font-size: 12px; color: #495057; margin-bottom: 8px; border-bottom: 1px solid #dee2e6; padding-bottom: 5px;">
                    STOCK AVAILABILITY
                </div>
                ${stockHtml}
            </div>
            <div class="col-md-5">
                <div style="font-weight: 600; font-size: 12px; color: #495057; margin-bottom: 8px; border-bottom: 1px solid #dee2e6; padding-bottom: 5px;">
                    TRANSACTION HISTORY
                </div>
                ${historyHtml}
            </div>
            <div class="col-md-3">
                <div style="font-weight: 600; font-size: 12px; color: #495057; margin-bottom: 8px; border-bottom: 1px solid #dee2e6; padding-bottom: 5px;">
                    SHIPPING & MARGIN
                </div>
                ${shippingHtml}
            </div>
        </div>
    `;

    return html;
}


/**
 * Fetch and refresh item info HTML for a given item code.
 * @param {object} frm - Form object
 * @param {string} item_code - Item code to fetch info for
 * @param {boolean} populate_tables - Also populate the hidden tables (for backward compatibility)
 */
function refresh_item_info_html(frm, item_code, populate_tables = false) {
    if (!item_code || !frm.doc.party_name) return;

    frappe.call({
        method: "avientek.events.quotation.get_item_all_details",
        args: {
            item_code: item_code,
            customer: frm.doc.party_name,
            price_list: frm.doc.selling_price_list,
            company: frm.doc.company,
        },
        callback(r) {
            if (!r.message) {
                frm.set_df_property("custom_item_info_html", "options",
                    '<div class="text-muted">No item data available</div>');
                frm.refresh_field("custom_item_info_html");
                return;
            }

            // Find the current item row to get calculated margin
            let item_row = (frm.doc.items || []).find(row => row.item_code === item_code);
            r.message.cal_margin = item_row ? flt(item_row.custom_margin_) : 0;

            // Populate tables for backward compatibility (only on new item selection)
            if (populate_tables) {
                (r.message.history || []).forEach(d => {
                    let h = frm.add_child("custom_history");
                    h.document_type = d.doctype;
                    h.document_id = d.name;
                    h.qty = d.qty;
                    h.unit_price = d.rate;
                });

                (r.message.stock || []).forEach(s => {
                    let st = frm.add_child("custom_stock");
                    st.company = s.company;
                    st.actual_stock = s.actual_stock;
                    st.free_stock = s.free_stock;
                    st.projected_stock = s.projected_stock;
                });

                if (r.message.shipment_margin) {
                    let sm = frm.add_child("custom_shipment_and_margin");
                    sm.ship_air = r.message.shipment_margin.ship_air;
                    sm.ship_sea = r.message.shipment_margin.ship_sea;
                    sm.std_margin = r.message.shipment_margin.std_margin;
                }
            }

            // Render HTML section
            let html = render_item_info_html(r.message, item_code);
            frm.set_df_property("custom_item_info_html", "options", html);
            frm.refresh_field("custom_item_info_html");
        }
    });
}


/**
 * Setup click handler on items grid to refresh item info when a row is clicked.
 */
function setup_items_grid_click_handler(frm) {
    // Remove existing handler to avoid duplicates
    frm.fields_dict.items.grid.wrapper.off('click.item_info');

    // Add click handler on grid rows
    frm.fields_dict.items.grid.wrapper.on('click.item_info', '.grid-row', function() {
        let $row = $(this);
        let idx = $row.data('idx');

        if (!idx) return;

        // Get the item from the row index (idx is 1-based)
        let item = frm.doc.items[idx - 1];
        if (item && item.item_code) {
            // Only refresh if it's a different item than currently displayed
            if (frm._current_item_info !== item.item_code) {
                frm._current_item_info = item.item_code;
                refresh_item_info_html(frm, item.item_code);
            }
        }
    });
}


/**
 * Dialog to update Special Price and Special Price Note on a submitted Quotation.
 * Does NOT recalculate Selling Price or Selling Amount.
 */
function show_update_special_price_dialog(frm) {
    let items = (frm.doc.items || []).map(row => ({
        name: row.name,
        item_code: row.item_code,
        qty: row.qty,
        custom_special_price: row.custom_special_price,
        custom_special_price_note: row.custom_special_price_note || "",
        custom_special_rate: row.custom_special_rate,
        custom_selling_price: row.custom_selling_price,
        custom_margin_: row.custom_margin_,
    }));

    let fields = [
        {
            fieldtype: "Table",
            fieldname: "items",
            label: __("Items"),
            cannot_add_rows: true,
            cannot_delete_rows: true,
            in_place_edit: true,
            data: items,
            fields: [
                { fieldname: "name", fieldtype: "Data", hidden: 1 },
                { fieldname: "item_code", fieldtype: "Data", label: __("Item Code"), in_list_view: 1, read_only: 1, columns: 2 },
                { fieldname: "qty", fieldtype: "Float", label: __("Qty"), in_list_view: 1, read_only: 1, columns: 1 },
                { fieldname: "custom_special_price", fieldtype: "Currency", label: __("Special Price"), in_list_view: 1, columns: 2 },
                { fieldname: "custom_special_price_note", fieldtype: "Data", label: __("Special Price Note"), in_list_view: 1, columns: 2 },
                { fieldname: "custom_special_rate", fieldtype: "Currency", label: __("Selling Price"), in_list_view: 1, read_only: 1, columns: 2 },
                { fieldname: "custom_margin_", fieldtype: "Percent", label: __("Margin %"), in_list_view: 1, read_only: 1, columns: 1 },
            ]
        }
    ];

    let d = new frappe.ui.Dialog({
        title: __("Update Special Price"),
        fields: fields,
        size: "extra-large",
        primary_action_label: __("Update"),
        primary_action(values) {
            let updated_items = (values.items || []).map(row => ({
                name: row.name,
                custom_special_price: row.custom_special_price,
                custom_special_price_note: row.custom_special_price_note,
            }));

            frappe.call({
                method: "avientek.events.quotation.update_special_price",
                args: {
                    quotation_name: frm.doc.name,
                    items: JSON.stringify(updated_items),
                },
                freeze: true,
                freeze_message: __("Updating Special Price..."),
                callback(r) {
                    if (r.message) {
                        d.hide();
                        frm.reload_doc();
                        frappe.show_alert({ message: __("Special Price updated"), indicator: "green" });
                    }
                }
            });
        }
    });

    d.show();
    // Widen dialog beyond extra-large default for better table readability
    d.$wrapper.find(".modal-dialog").css("max-width", "1100px");
}
