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
        // Use callback to ensure form state is clean after reload
        frm.reload_doc().then(() => {
            // Reset discount/incentive applied flags after reload
            frm._discount_applied = true;
            frm._incentive_applied = true;
            // Ensure form is marked as clean (not dirty)
            frm.doc.__unsaved = 0;
        });
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
    },

    onload(frm) {
        frm.set_query('custom_quote_project', function () {
            return { query: 'avientek.events.sales_person_permission.get_project_quotation_for_user' };
        });
    },

    selling_price_list(frm) {
        if (!frm.doc.selling_price_list) return;
        // Reload defaults for all existing items
        frm.doc.items.forEach(item => {
            if (item.item_code) {
                load_item_defaults(frm, item.doctype, item.name);
            }
        });
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

        // Pass item margin data (may be empty for new items)
        let item_margin = {
            margin_percent: row.custom_margin_ || 0,
            margin_value: row.custom_margin_value || 0,
            selling_price: row.custom_selling_price || 0,
            cogs: row.custom_cogs || 0
        };

        // Load and render item info (with table population for backward compatibility)
        refresh_item_info_html(frm, row.item_code, true, item_margin);

        // Load item defaults (single server call)
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
 */
function calculate_all_preview(frm, cdt, cdn) {
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
        },
        callback(r) {
            if (!r.message) return;
            let d = r.message;

            // Always set prices
            frappe.model.set_value(cdt, cdn, "custom_standard_price_", d.custom_standard_price_ || 0);
            frappe.model.set_value(cdt, cdn, "custom_special_price", d.custom_special_price || 0);

            // Set defaults only if field is currently empty (preserve user edits)
            if (!row.shipping_per)    frappe.model.set_value(cdt, cdn, "shipping_per", d.shipping_per_air || 0);
            if (!row.custom_transport_) frappe.model.set_value(cdt, cdn, "custom_transport_", d.custom_transport_ || 0);
            if (!row.custom_finance_) frappe.model.set_value(cdt, cdn, "custom_finance_", d.custom_finance_ || 0);
            if (!row.std_margin_per)  frappe.model.set_value(cdt, cdn, "std_margin_per", d.std_margin_per || 0);
            if (!row.custom_customs_) frappe.model.set_value(cdt, cdn, "custom_customs_", d.custom_customs_ || 0);

            // Run preview after defaults are loaded
            calculate_all_preview(frm, cdt, cdn);
        }
    });
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
 * Render item information (stock, history, shipment/margin, calculated margin) as HTML.
 * Uses Frappe's row/col classes for proper responsive columns.
 * @param {object} data - Data from get_item_all_details (stock, history, shipment_margin)
 * @param {object} item_margin - Calculated margin from selected item row (optional)
 */
function render_item_info_html(data, item_margin = null) {
    // Stock section - list format
    let stockHtml = '';
    if (data.stock && data.stock.length > 0) {
        stockHtml = `
            <table class="table table-sm table-borderless" style="margin: 0; font-size: 12px;">
                <thead>
                    <tr style="font-size: 10px; color: #888; text-transform: uppercase;">
                        <th>Company</th>
                        <th style="text-align: right;">Free</th>
                        <th style="text-align: right;">Actual</th>
                        <th style="text-align: right;">Projected</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.stock.map(s => {
                        let statusColor = s.free_stock > 0 ? '#28a745' : '#dc3545';
                        let statusBg = s.free_stock > 0 ? '#d4edda' : '#f8d7da';
                        let projColor = s.projected_stock > 0 ? '#007bff' : '#6c757d';
                        return `
                            <tr>
                                <td>${s.company}</td>
                                <td style="text-align: right;">
                                    <span style="background:${statusBg}; color:${statusColor}; padding: 2px 8px; border-radius: 4px; font-weight: bold;">
                                        ${s.free_stock}
                                    </span>
                                </td>
                                <td style="text-align: right; color: #888;">${s.actual_stock}</td>
                                <td style="text-align: right; color: ${projColor}; font-weight: 500;">${s.projected_stock}</td>
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
        shippingHtml = `
            <div class="row" style="text-align: center;">
                <div class="col-4">
                    <div style="font-size: 10px; color: #888;">AIR</div>
                    <div style="font-size: 16px; font-weight: bold;">${sm.ship_air || 0}%</div>
                </div>
                <div class="col-4">
                    <div style="font-size: 10px; color: #888;">SEA</div>
                    <div style="font-size: 16px; font-weight: bold;">${sm.ship_sea || 0}%</div>
                </div>
                <div class="col-4">
                    <div style="font-size: 10px; color: #888;">MARGIN</div>
                    <div style="font-size: 16px; font-weight: bold;">${sm.std_margin || 0}%</div>
                </div>
            </div>
        `;
    } else {
        shippingHtml = '<span class="text-muted">No data</span>';
    }

    // Calculated Margin section (from selected item row)
    let marginHtml = '';
    if (item_margin && (item_margin.margin_percent || item_margin.margin_value)) {
        let marginColor = item_margin.margin_percent >= 10 ? '#28a745' : (item_margin.margin_percent >= 5 ? '#ffc107' : '#dc3545');
        marginHtml = `
            <div style="text-align: center;">
                <div style="font-size: 24px; font-weight: bold; color: ${marginColor};">
                    ${flt(item_margin.margin_percent, 2)}%
                </div>
                <div style="font-size: 12px; color: #666;">
                    ${format_currency(item_margin.margin_value)}
                </div>
                <div style="font-size: 10px; color: #888; margin-top: 5px;">
                    Sell: ${format_currency(item_margin.selling_price)}<br>
                    Cost: ${format_currency(item_margin.cogs)}
                </div>
            </div>
        `;
    } else {
        marginHtml = '<span class="text-muted">Select item to view</span>';
    }

    // Combine into 4-column layout
    let html = `
        <div class="row" style="margin: 0 0 15px 0; padding: 10px; background: #f8f9fa; border-radius: 8px;">
            <div class="col-md-3">
                <div style="font-weight: 600; font-size: 12px; color: #495057; margin-bottom: 8px; border-bottom: 1px solid #dee2e6; padding-bottom: 5px;">
                    STOCK AVAILABILITY
                </div>
                ${stockHtml}
            </div>
            <div class="col-md-4">
                <div style="font-weight: 600; font-size: 12px; color: #495057; margin-bottom: 8px; border-bottom: 1px solid #dee2e6; padding-bottom: 5px;">
                    TRANSACTION HISTORY
                </div>
                ${historyHtml}
            </div>
            <div class="col-md-2">
                <div style="font-weight: 600; font-size: 12px; color: #495057; margin-bottom: 8px; border-bottom: 1px solid #dee2e6; padding-bottom: 5px;">
                    SHIPPING
                </div>
                ${shippingHtml}
            </div>
            <div class="col-md-3">
                <div style="font-weight: 600; font-size: 12px; color: #495057; margin-bottom: 8px; border-bottom: 1px solid #dee2e6; padding-bottom: 5px;">
                    CALCULATED MARGIN
                </div>
                ${marginHtml}
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
function refresh_item_info_html(frm, item_code, populate_tables = false, item_margin = null) {
    if (!item_code || !frm.doc.party_name) return;

    frappe.call({
        method: "avientek.events.quotation.get_item_all_details",
        args: {
            item_code: item_code,
            customer: frm.doc.party_name,
            price_list: frm.doc.selling_price_list
        },
        callback(r) {
            if (!r.message) {
                frm.set_df_property("custom_item_info_html", "options",
                    '<div class="text-muted">No item data available</div>');
                frm.refresh_field("custom_item_info_html");
                return;
            }

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

            // Render HTML section with item margin data
            let html = render_item_info_html(r.message, item_margin);
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
            // Always refresh to show current item's margin (even if same item)
            frm._current_item_info = item.item_code;
            // Pass item margin data
            let item_margin = {
                margin_percent: item.custom_margin_ || 0,
                margin_value: item.custom_margin_value || 0,
                selling_price: item.custom_selling_price || 0,
                cogs: item.custom_cogs || 0
            };
            refresh_item_info_html(frm, item.item_code, false, item_margin);
        }
    });
}
