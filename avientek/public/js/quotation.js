// ──────────────────────────────────────────────────────────────
// Quotation JS — Thin UI layer
// All authoritative calculations run server-side (before_save).
// JS only provides instant preview + handles UI events.
// ──────────────────────────────────────────────────────────────

// ──────────────────────────────────────────────────────────────
// High-Probability lock UI hint (Sridhar 2026-05-06).
// Server enforces (avientek.api.quotation_high_probability.before_save).
// JS just renders the form read-only + adds a banner so the user
// understands BEFORE they try to edit. Whitelisted roles see a
// different banner and editing stays enabled.
// ──────────────────────────────────────────────────────────────
const HIGH_PROB_THRESHOLD = 75;
// Default whitelist — overwritten on first form load by the server's
// Avientek Settings via avientek.api.quotation_high_probability
// .get_role_config (Sridhar 2026-05-06: roles are now configurable).
let _HIGH_PROB_WHITELIST = [
    "GM-CS", "CS", "Sales support L2", "System Manager", "Administrator",
];
let _HIGH_PROB_CONFIG_LOADED = false;

function _load_high_prob_role_config() {
    // Cache once per page load — the settings doc is small and stable.
    if (_HIGH_PROB_CONFIG_LOADED) { return Promise.resolve(); }
    return frappe.call({
        method: "avientek.api.quotation_high_probability.get_role_config",
    }).then(r => {
        if (r.message && r.message.whitelisted) {
            _HIGH_PROB_WHITELIST = r.message.whitelisted;
        }
        _HIGH_PROB_CONFIG_LOADED = true;
    }).catch(() => {
        // Network blip — keep the defaults; the server is authoritative
        // anyway, JS lock is just a UX hint.
        _HIGH_PROB_CONFIG_LOADED = true;
    });
}

function _user_is_whitelisted_for_high_prob() {
    const roles = frappe.user_roles || [];
    return _HIGH_PROB_WHITELIST.some(r => roles.indexOf(r) !== -1);
}

function _so_button_conditions_met(frm) {
    if (frm.is_new()) { return false; }
    const isApproved = (frm.doc.workflow_state || "") === "Approved";
    const probRaw = (frm.doc.probabilities || "").toString().replace("%", "").trim();
    const probNum = parseInt(probRaw || frm.doc.probability || 0, 10) || 0;
    const has100 = (probNum === 100);
    // Sridhar 2026-05-29: also block Create→Sales Order when there's
    // a pending probability change. The visual probability is back at
    // 100% so the basic gate passes, but if L2 approver hasn't acted
    // yet we shouldn't let sales push to SO.
    const hasPendingProb = (frm.doc.pending_probability_status || "") === "Pending";
    return isApproved && has100 && !hasPendingProb;
}


function _install_so_button_interceptor(frm) {
    // Sridhar 2026-05-29 round 4: previous DOM-based strip didn't work
    // because Frappe v15 renders Create-dropdown items LAZILY (only on
    // dropdown open). My setTimeout strip kept finding 0 elements in
    // the DOM. New approach: monkey-patch frm.add_custom_button so the
    // SO/SI buttons NEVER get registered when conditions aren't met.
    // Installed once per form via the `setup` event so it's in place
    // before ERPNext's refresh handler tries to add the button.
    if (frm.__avk_so_intercept_installed) return;
    frm.__avk_so_intercept_installed = true;

    const orig_add = frm.add_custom_button.bind(frm);
    frm.add_custom_button = function(label, action, group) {
        const labelStr = (typeof label === "string") ? label : ((label && label.toString) ? label.toString() : "");
        const groupStr = (typeof group === "string") ? group : ((group && group.toString) ? group.toString() : "");
        const blocked = (labelStr === __("Sales Order") || labelStr === __("Sales Invoice"))
                        && (groupStr === __("Create") || groupStr === "Create");
        if (blocked && !_so_button_conditions_met(frm)) {
            // Silently skip — caller's button is never registered.
            return;
        }
        return orig_add(label, action, group);
    };
}


function _toggle_create_button_visibility(frm) {
    // Sridhar 2026-05-29 round 5: instead of trying to remove individual
    // items from the lazy-rendered Create dropdown, hide the whole
    // Create button when conditions aren't met. The Create button is
    // ALWAYS in the DOM (not lazy), so this works reliably regardless
    // of Frappe's render timing.
    if (frm.is_new()) { return; }
    const show = _so_button_conditions_met(frm);
    const _apply = function() {
        // Sridhar 2026-05-29 — exact snippet pattern that worked when
        // pasted into DevTools (Hidden count: 1, Create button gone).
        // Conditional show/hide based on `show` flag rather than the
        // unconditional hide in the test snippet, but the selector +
        // text matching are identical.
        let hidden = 0;
        try {
            $('.custom-actions .inner-group-button').each(function() {
                const $g = $(this);
                const $btn = $g.children('button').first();
                const txt = ($btn.text() || "").replace(/\s+/g, " ").trim();
                if (/^Create($|\s|▾)/.test(txt)) {
                    $g.css('display', show ? '' : 'none');
                    if (!show) { hidden++; }
                }
            });
        } catch (e) {}
        return hidden;
    };
    _apply();
    setTimeout(_apply, 250);
    setTimeout(_apply, 1200);
    setTimeout(_apply, 2500);
    setTimeout(_apply, 5000);

    // Sridhar 2026-05-29 round 7: setTimeouts catch most cases but
    // can miss if Frappe adds the Create button after our 5s window
    // (slow loads, deferred renders). Install a MutationObserver once
    // per form that re-applies the hide whenever .custom-actions
    // children change. Self-destructs after the form unloads.
    if (!frm.__avk_create_observer) {
        const target = document.querySelector('.custom-actions') || document.body;
        try {
            const obs = new MutationObserver(function() {
                // Re-evaluate show flag in case workflow_state changed
                const _show = _so_button_conditions_met(frm);
                $('.custom-actions .inner-group-button').each(function() {
                    const $g = $(this);
                    const $btn = $g.children('button').first();
                    const txt = ($btn.text() || "").replace(/\s+/g, " ").trim();
                    if (/^Create($|\s|▾)/.test(txt)) {
                        $g.css('display', _show ? '' : 'none');
                    }
                });
            });
            obs.observe(target, { childList: true, subtree: true });
            frm.__avk_create_observer = obs;
        } catch (e) {}
    }
}


// Venkatesh/Rahul 2026-06-11 ERP-TKT-31: Quote print should be gated
// on Approval — users keep generating PDFs of draft/pending quotes and
// share them with customers, then the price changes on L2 approval and
// the customer was quoted the wrong number. Server-side `before_print`
// hook is the hard backstop (avientek.events.quotation
// .block_print_unless_approved); this is the UX layer so the user
// doesn't see the option at all until the quote is Approved.
const _QN_PRINT_ALLOWED_STATES = new Set([
    "Approved",          // V3 terminal-approved
    "Submitted",         // legacy
    "Order Placed",      // post-conversion to SO
    "Quotation Closed",  // post-conversion / explicit close
]);
function _strip_print_buttons_unless_approved(frm) {
    if (frm.is_new()) { return; }
    const ws = frm.doc.workflow_state || "";
    if (_QN_PRINT_ALLOWED_STATES.has(ws)) { return; }

    // System Manager / Administrator can always print — audit trail.
    const roles = frappe.user_roles || [];
    if (roles.indexOf("System Manager") >= 0 || frappe.session.user === "Administrator") {
        return;
    }

    // Frappe v15 renders Print / Email / PDF as menu items under the
    // "..." dropdown. The DOM hooks are stable across v15 minor
    // versions; the data-label attribute makes the selector resilient.
    // Run inside requestAnimationFrame so we win the race with
    // Frappe's own menu population.
    const hide_print_menu_items = () => {
        try {
            const $menu = (frm.page && frm.page.menu) ? frm.page.menu : null;
            if (!$menu || !$menu.length) { return; }
            // Match labels with translation safety — Frappe uses __()
            // so the label DOM text may be translated. Match against
            // the original English token too as a fallback.
            const labels_to_hide = ["Print", __("Print"), "Email", __("Email"), "PDF", __("PDF")];
            $menu.find('a.dropdown-item, .dropdown-item, a').each(function () {
                const txt = ($(this).text() || "").trim();
                if (labels_to_hide.indexOf(txt) >= 0) {
                    $(this).closest("li, .dropdown-item-wrap").hide();
                }
            });
        } catch (e) {
            console.warn("strip_print_buttons:", e);
        }
    };
    requestAnimationFrame(hide_print_menu_items);
    // Run twice — once after the next paint, once after Frappe's
    // own menu repopulation. Cheap and idempotent.
    setTimeout(hide_print_menu_items, 200);
}


function _strip_create_buttons_unless_approved(frm) {
    // Round-4 legacy interceptor still removes the SO/SI custom-button
    // registration as a defensive secondary layer. The primary defence
    // is now _toggle_create_button_visibility which hides the whole
    // Create dropdown trigger when conditions aren't met.
    _toggle_create_button_visibility(frm);
    if (frm.is_new()) { return; }

    const APPROVED_STATES = new Set(["Approved"]);
    const isApproved = APPROVED_STATES.has(frm.doc.workflow_state || "");

    // Probability lives in EITHER `probabilities` (Data, "100%") OR
    // `probability` (Int). Read whichever is set; tolerate "%" suffix
    // and whitespace.
    const probRaw = (frm.doc.probabilities || "").toString().replace("%", "").trim();
    const probNum = parseInt(probRaw || frm.doc.probability || 0, 10) || 0;
    const is100 = (probNum === 100);

    if (isApproved && is100) { return; }

    const _strip = function() {
        // Try Frappe's API first
        try { frm.remove_custom_button(__("Sales Order"), __("Create")); } catch (e) {}
        try { frm.remove_custom_button(__("Sales Invoice"), __("Create")); } catch (e) {}
        // Belt-and-braces: directly remove the dropdown li from the
        // Create group if Frappe's API didn't catch them. Matches the
        // anchor by exact label text.
        try {
            $(frm.page.btn_secondary_group || frm.page.inner_toolbar || document)
                .find('.dropdown-menu li a, ul li a')
                .filter(function() {
                    const t = ($(this).text() || "").trim();
                    return t === "Sales Order" || t === "Sales Invoice";
                })
                .closest("li").remove();
        } catch (e) {}
        // Page-wide fallback — covers any other dropdown rendering
        try {
            $('.frappe-form .dropdown-menu li a, .page-actions .dropdown-menu li a')
                .filter(function() {
                    const t = ($(this).text() || "").trim();
                    return t === "Sales Order" || t === "Sales Invoice";
                })
                .closest("li").remove();
        } catch (e) {}
    };
    _strip();
    // Delayed re-strip — covers races where Frappe finishes adding
    // standard buttons after our refresh handler runs.
    setTimeout(_strip, 250);
    setTimeout(_strip, 1200);
    setTimeout(_strip, 2500);
}


function _apply_high_probability_lock(frm) {
    if (frm.is_new()) { return; }
    const prob = parseFloat(frm.doc.probability || 0);
    if (prob < HIGH_PROB_THRESHOLD) {
        frm.dashboard.clear_headline();
        return;
    }
    if (_user_is_whitelisted_for_high_prob()) {
        frm.dashboard.set_headline(
            __("Probability is {0}% — high-prob lock waived for your role.",
                [prob]),
            "yellow",
        );
        return;
    }
    // Lock every field except `probability` itself.
    const meta = frappe.get_meta(frm.doctype) || {};
    (meta.fields || []).forEach(function (f) {
        if (!f.fieldname || f.fieldname === "probability") { return; }
        frm.set_df_property(f.fieldname, "read_only", 1);
    });
    frm.dashboard.set_headline(
        __("Quotation locked: probability {0}% (>= {1}%). " +
           "Only the Probability field is editable, and only to bump it " +
           "to 100%. To Cancel / Amend / Resubmit, scroll down to the " +
           "<b>Document Approval</b> section, tick <i>Request for Update</i> " +
           "or <i>Cancellation Check</i>, fill the note, and Save.",
           [prob, HIGH_PROB_THRESHOLD]),
        "orange",
    );
}

frappe.ui.form.on('Quotation', {

    setup(frm) {
        // Sridhar 2026-05-29 round 4: install the add_custom_button
        // interceptor BEFORE any refresh fires. Frappe v15 renders
        // Create-dropdown items lazily so any reactive DOM strip races
        // and finds zero elements. Intercepting at registration time
        // means SO/SI never enter the button cache.
        _install_so_button_interceptor(frm);
    },

    refresh(frm) {
        _load_high_prob_role_config().then(() => {
            _apply_high_probability_lock(frm);
        });
        // Defensive safety net — the setup-time interceptor is the
        // primary defence, but if any code path bypasses it (e.g., a
        // future Client Script using a different button API) this
        // reactive strip catches the leak.
        _strip_create_buttons_unless_approved(frm);
        // Venkatesh/Rahul 2026-06-11 ERP-TKT-31: hide Print / Email /
        // PDF menu items unless the Quotation is Approved (or a
        // downstream state). Server-side `before_print` hook on
        // Quotation throws as a hard backstop — this is the UX layer
        // so the user doesn't even see the option pre-approval.
        _strip_print_buttons_unless_approved(frm);
    },

    probability(frm) {
        _load_high_prob_role_config().then(() => {
            _apply_high_probability_lock(frm);
        });
    },

    // ── Save lifecycle ──────────────────────────────────────
    before_save(frm) {
        run_full_calculation_preview(frm);
    },

    after_save(frm) {
        // Show margin warning after save (approval_status is now set by server)
        frm._margin_warning_shown = false; // reset so warning shows again
        var warnings = [];
        (frm.doc.custom_quotation_brand_summary || []).forEach(function (row) {
            if (row.approval_status === "APPROVED_WITH_WARNING") {
                warnings.push(
                    __("Brand <b>{0}</b>: Margin {1}% is below standard {2}%, but historical overall margin is healthy.", [
                        row.brand, row.margin_percent, row.std_margin_percent
                    ])
                );
            }
        });
        if (warnings.length) {
            frm.dashboard.set_headline(
                '<span style="color: #e67e22; font-weight: bold;">⚠ Margin Warning: ' +
                warnings.join(" | ") + '</span>'
            );
            frappe.msgprint({
                title: __("Margin Warning"),
                message: warnings.join("<br><br>"),
                indicator: "orange",
            });
            frm._margin_warning_shown = true;
        }
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
            // ── Client Script: "Quot" - auto-set sales_person from customer ──
            if (customer_doc.sales_team && customer_doc.sales_team.length) {
                frm.set_value("sales_person", customer_doc.sales_team[0].sales_person);
            }

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
                method: 'avientek.events.quotation.get_customer_outstanding',
                args: { customer: frm.doc.party_name, company: company },
                callback(r) {
                    frm.set_value('custom_outstanding', flt(r.message));
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
                method: 'avientek.events.quotation.get_customer_outstanding',
                args: { customer: frm.doc.customer, company: company },
                callback(r) {
                    frm.set_value('outstanding_credit', flt(r.message));
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

    // Discount handlers are managed via calculate_taxes_and_totals override
    // in the main refresh() handler below.

    // ── Discount Type Selection ─────────────────────────────
    custom_discount_type(frm) {
        toggle_discount_fields(frm);
        // Mark discount as not applied when type changes
        frm._discount_applied = false;
        toggle_apply_discount_button(frm);
    },

    custom_discount_amount_value(frm) {
        if (frm._applying_discount) return; // skip during Apply Discount
        frm._discount_applied = false;
        toggle_apply_discount_button(frm);
    },

    custom_discount_(frm) {
        if (frm._applying_discount) return; // skip during Apply Discount
        frm._discount_applied = false;
        toggle_apply_discount_button(frm);
    },

    // When Additional Discount changes, enforce mutual exclusion + instant preview
    additional_discount_percentage(frm) {
        // If user cleared percentage to 0, also clear amount to break circular dependency
        if (flt(frm.doc.additional_discount_percentage) === 0) {
            frm.doc.discount_amount = 0;
            frm.doc.base_discount_amount = 0;
            (frm.doc.items || []).forEach(row => { row.custom_addl_discount_amount = 0; });
        }
        enforce_discount_mutual_exclusion(frm, "addl");
        run_full_calculation_preview(frm);
    },

    discount_amount(frm) {
        // If user cleared amount to 0, also clear percentage to break circular dependency
        if (flt(frm.doc.discount_amount) === 0) {
            frm.doc.additional_discount_percentage = 0;
            frm.doc.base_discount_amount = 0;
            (frm.doc.items || []).forEach(row => { row.custom_addl_discount_amount = 0; });
        }
        enforce_discount_mutual_exclusion(frm, "addl");
        run_full_calculation_preview(frm);
    },

    // ── Discount (instant client-side) ─────────────────────
    custom_apply_discount(frm) {
        let discount_type = frm.doc.custom_discount_type || "Amount";
        let discount_amount = 0;

        let items = frm.doc.items || [];
        if (!items.length) {
            frappe.msgprint(__("No items available to apply discount"));
            return;
        }

        // Auto-clear Additional Discount only when applying a POSITIVE Disc & Inc value
        // (clearing Disc & Inc to 0 should NOT touch Additional Discount)
        let has_positive_disc = flt(frm.doc.custom_discount_amount_value) > 0 || flt(frm.doc.custom_discount_) > 0;
        if (has_positive_disc) {
            enforce_discount_mutual_exclusion(frm, "disc_inc");
        }

        // Guard flag: prevent custom_discount_amount_value handler from
        // resetting _discount_applied during set_value calls below
        frm._applying_discount = true;

        // Reset all items to pre-discount selling prices first
        items.forEach(row => {
            calculate_all_preview(frm, row.doctype, row.name);
        });

        // Now read fresh total selling value (before discount)
        let total_selling = 0;
        items.forEach(row => {
            total_selling += flt(row.custom_selling_price) || flt(row.amount) || 0;
        });

        if (total_selling <= 0) {
            frappe.msgprint(__("Invalid selling amount"));
            return;
        }

        if (discount_type === "Percentage") {
            if (frm.doc.custom_discount_ == null || frm.doc.custom_discount_ === "") {
                frappe.msgprint(__("Please enter discount percentage"));
                return;
            }
            discount_amount = (total_selling * flt(frm.doc.custom_discount_)) / 100;
            frm.set_value("custom_discount_amount_value", discount_amount);
        } else {
            if (frm.doc.custom_discount_amount_value == null || frm.doc.custom_discount_amount_value === "") {
                frappe.msgprint(__("Please enter discount amount"));
                return;
            }
            discount_amount = flt(frm.doc.custom_discount_amount_value);
            if (total_selling > 0) {
                frm.set_value("custom_discount_", (discount_amount / total_selling) * 100);
            }
        }

        // Instant client-side proportional distribution
        items.forEach(row => {
            let selling = flt(row.custom_selling_price) || flt(row.amount) || 0;
            let qty = flt(row.qty) || 1;
            let cogs = flt(row.custom_cogs);

            let share = total_selling ? (selling / total_selling) : 0;
            let item_discount = flt(discount_amount * share, 4);

            let new_selling = Math.max(selling - item_discount, 0);
            let new_rate = flt(new_selling / qty, 4);
            let new_margin_val = flt(new_selling - cogs, 4);
            let new_margin_pct = new_selling ? flt((new_margin_val / new_selling) * 100, 4) : 0;

            let conversion_rate = flt(frm.doc.conversion_rate) || 1;
            row.custom_discount_amount_value = flt(item_discount / qty, 4);
            row.custom_discount_amount_qty   = flt(item_discount, 4);
            row.custom_special_rate          = new_rate;
            row.custom_selling_price         = new_selling;
            row.custom_total_                = new_selling;
            row.price_list_rate              = new_rate;
            row.base_price_list_rate         = flt(new_rate * conversion_rate);
            row.rate                         = new_rate;
            row.base_rate                    = flt(new_rate * conversion_rate);
            row.net_rate                     = new_rate;
            row.amount                       = new_selling;
            row.base_amount                  = flt(new_selling * conversion_rate);
            row.net_amount                   = new_selling;
            row.base_net_amount              = flt(new_selling * conversion_rate);
            row.custom_margin_value          = new_margin_val;
            row.custom_margin_               = new_margin_pct;
        });

        frm.refresh_field("items");
        update_doc_totals_preview(frm);

        // Clear guard flag and mark discount as applied
        frm._applying_discount = false;
        frm._discount_applied = true;
        toggle_apply_discount_button(frm);

        frm.dirty();
        frappe.show_alert({message: __("Discount applied"), indicator: "green"});
    },

    // ── Incentive Type Selection ─────────────────────────────
    custom_incentive_type(frm) {
        toggle_incentive_fields(frm);
        // Mark incentive as not applied when type changes
        frm._incentive_applied = false;
        toggle_apply_incentive_button(frm);
    },

    custom_distribute_incentive_based_on(frm) {
        toggle_incentive_readonly(frm);
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

        let items = frm.doc.items || [];
        if (!items.length) {
            frappe.msgprint(__("No items available to apply incentive"));
            return;
        }

        // Calculate total SP * qty
        let total_sp = 0;
        items.forEach(row => {
            total_sp += flt(row.custom_special_price) * (flt(row.qty) || 1);
        });

        if (!total_sp) {
            frappe.msgprint(__("Items have no Special Price set"));
            return;
        }

        if (incentive_type === "Percentage") {
            if (frm.doc.custom_incentive_ == null || frm.doc.custom_incentive_ === "") {
                frappe.msgprint(__("Please enter incentive percentage"));
                return;
            }
            incentive_amount = (total_sp * flt(frm.doc.custom_incentive_)) / 100;
            frm.set_value("custom_incentive_amount", incentive_amount);
        } else {
            if (frm.doc.custom_incentive_amount == null || frm.doc.custom_incentive_amount === "") {
                frappe.msgprint(__("Please enter incentive amount"));
                return;
            }
            incentive_amount = flt(frm.doc.custom_incentive_amount);
            if (total_sp > 0) {
                frm.set_value("custom_incentive_", (incentive_amount / total_sp) * 100);
            }
        }

        // Instant client-side distribution across items
        let mode = frm.doc.custom_distribute_incentive_based_on || "Amount";
        items.forEach((row, idx) => {
            let qty = flt(row.qty) || 1;
            let sp = flt(row.custom_special_price);
            let row_incentive = 0;

            if (mode === "Distributed Equally") {
                row_incentive = flt(incentive_amount / items.length, 4);
            } else if (mode === "Distributed Manually") {
                return;  // skip — user sets item-level values
            } else {
                // "Amount" — proportional to sp * qty
                row_incentive = total_sp ? flt((sp * qty / total_sp) * incentive_amount, 4) : 0;
            }

            // Set item-level incentive % directly on the row object (NOT async set_value)
            // so that calculate_all_preview picks it up immediately
            let item_incentive_pct = (sp * qty) ? flt(row_incentive / (sp * qty) * 100, 4) : 0;
            row.custom_incentive_ = item_incentive_pct;
        });

        // Recalculate all items preview (incentive % is already set synchronously above)
        items.forEach(row => {
            calculate_all_preview(frm, row.doctype, row.name);
        });

        // Re-apply discount on top if one exists
        let discount_amount = flt(frm.doc.custom_discount_amount_value);
        if (discount_amount > 0) {
            reapply_discount_preview(frm, discount_amount);
        }

        update_doc_totals_preview(frm);

        // Mark incentive as applied and hide button
        frm._incentive_applied = true;
        toggle_apply_incentive_button(frm);

        frm.dirty();
        frappe.show_alert({message: __("Incentive applied"), indicator: "green"});
    },

    // ── Refresh / Onload ────────────────────────────────────
    refresh(frm) {
        // Diagnostic button — for the India company, surfaces why any
        // items in this Quotation will trip the "Items not covered under
        // GST cannot be clubbed..." validator. Pulls item codes straight
        // off the current form, so it works even on unsaved drafts.
        if (frm.doc.company === "Avientek Electronics Trading PVT. LTD") {
            frm.add_custom_button(__("Check GST Status"), function () {
                let codes = (frm.doc.items || [])
                    .map(r => r.item_code)
                    .filter(Boolean);
                if (!codes.length) {
                    frappe.msgprint(__("No items on this Quotation to check."));
                    return;
                }
                frappe.call({
                    method: "avientek.api.quotation_access.check_items_gst_status",
                    args: { item_codes: JSON.stringify(codes) },
                    callback: function (r) {
                        if (!r.message) return;
                        if (r.message.error) {
                            frappe.msgprint(r.message.error);
                            return;
                        }
                        let summary = r.message.summary || {};
                        let items = r.message.items || [];
                        let rows = items.map(it => `
                            <tr style="${it.will_block_mixed_save ? 'background:#ffecec;' : ''}">
                                <td>${frappe.utils.escape_html(it.item_code || "")}</td>
                                <td>${frappe.utils.escape_html(it.gst_hsn_code || "—")}</td>
                                <td><b>${frappe.utils.escape_html(it.gst_treatment_effective || "")}</b></td>
                                <td>${it.will_block_mixed_save ? "❌ YES" : "✅ OK"}</td>
                                <td style="font-size:11px;">${frappe.utils.escape_html(it.diagnosis || "")}</td>
                            </tr>`).join("");
                        let html = `
                            <p><b>${summary.total || 0}</b> items — <b style="color:red;">${summary.will_block || 0}</b> blocking, <b style="color:green;">${summary.ok || 0}</b> ok.</p>
                            <table class="table table-bordered" style="font-size:12px;">
                                <thead>
                                    <tr>
                                        <th>Item Code</th>
                                        <th>HSN</th>
                                        <th>GST Treatment</th>
                                        <th>Blocks?</th>
                                        <th>Why</th>
                                    </tr>
                                </thead>
                                <tbody>${rows}</tbody>
                            </table>
                            <p style="margin-top:10px;"><b>Fix:</b> For each blocking row, open the Item master and either (a) set HSN/SAC code and link an Item Tax Template whose GST Treatment is "Taxable", or (b) uncheck is_non_gst if it's wrongly marked.</p>
                        `;
                        frappe.msgprint({
                            title: __("GST Status for Items on this Quotation"),
                            message: html,
                            wide: true,
                        });
                    },
                });
            }, __("GST"));
        }

        // Show margin warning for APPROVED_WITH_WARNING brands
        if (frm.doc.custom_quotation_brand_summary && frm.doc.docstatus === 0) {
            var warnings = [];
            (frm.doc.custom_quotation_brand_summary || []).forEach(function (row) {
                if (row.approval_status === "APPROVED_WITH_WARNING") {
                    warnings.push(
                        __("Brand <b>{0}</b>: Margin {1}% is below standard {2}%, but historical overall margin is healthy.", [
                            row.brand, row.margin_percent, row.std_margin_percent
                        ])
                    );
                }
            });
            if (warnings.length) {
                // 1. Dashboard headline (persistent orange bar)
                frm.dashboard.set_headline(
                    '<span style="color: #e67e22; font-weight: bold;">⚠ Margin Warning: ' +
                    warnings.join(" | ") + '</span>'
                );
                // 2. Show dialog once per form load (not on every refresh)
                if (!frm._margin_warning_shown) {
                    frm._margin_warning_shown = true;
                    frappe.msgprint({
                        title: __("Margin Warning"),
                        message: warnings.join("<br><br>"),
                        indicator: "orange",
                    });
                }
            }
        }

        // Override ERPNext's calculate_taxes_and_totals to prevent it from
        // overwriting our custom selling price calculations.
        // ERPNext calls this after get_item_details, qty changes, etc.
        // and recomputes totals from its cached price_list_rate (= Item Price),
        // ignoring our calculated selling price.  By overriding, we ensure
        // our values always win.
        if (!frm._calc_override_applied) {
            frm.cscript.calculate_taxes_and_totals = function() {
                run_full_calculation_preview(frm);
            };
            frm._calc_override_applied = true;
        }

        // Ensure frappe.dynamic_link is set (ERPNext controller sets it but
        // timing can cause it to be undefined when address_query fires)
        if (frm.doc.quotation_to && frm.doc.party_name) {
            frappe.dynamic_link = {
                doc: frm.doc,
                fieldname: "party_name",
                doctype: frm.doc.quotation_to,
            };
        }

        update_custom_service_totals(frm);

        frm.set_query("selling_price_list", function () {
            return { filters: { currency: frm.doc.currency } };
        });

        // Filter customers by company + Customer Group + Sales Person
        // Only override for Customer — Leave Lead/Prospect to ERPNext's default query
        if (frm.doc.quotation_to === 'Customer') {
            frm.set_query('party_name', function () {
                if (frm.doc.quotation_to !== 'Customer') return {};
                if ((frm._permitted_customer_groups && frm._permitted_customer_groups.length) ||
                    (frm._permitted_sales_persons && frm._permitted_sales_persons.length)) {
                    return {
                        query: "avientek.api.quotation_access.get_filtered_customers",
                        filters: { company: frm.doc.company || "" }
                    };
                }
                if (frm.doc.company) {
                    return { filters: { company: frm.doc.company } };
                }
                return {};
            });
        }

        // Filter items by permitted Brands and Item Groups
        frm.set_query('item_code', 'items', function () {
            let filters = {};
            if (frm._permitted_brands && frm._permitted_brands.length) {
                filters.brand = ["in", frm._permitted_brands];
            }
            if (frm._permitted_item_groups && frm._permitted_item_groups.length) {
                filters.item_group = ["in", frm._permitted_item_groups];
            }
            if (Object.keys(filters).length) return { filters: filters };
        });

        // Filter Sales Person by permitted values (sales_team child table, if exists)
        if (frm.fields_dict.sales_team) {
            frm.set_query('sales_person', 'sales_team', function () {
                if (frm._permitted_sales_persons && frm._permitted_sales_persons.length) {
                    return { filters: { name: ["in", frm._permitted_sales_persons] } };
                }
            });
        }

        // Fetch user permission restrictions once (cached in frm)
        if (!frm._perms_loaded) {
            frm._perms_loaded = true;
            frappe.call({
                method: "avientek.api.quotation_access.get_user_restrictions",
                async: true,
                callback: function (r) {
                    let d = r.message || {};
                    frm._permitted_brands = d.brands || [];
                    frm._permitted_item_groups = d.item_groups || [];
                    frm._permitted_customer_groups = d.customer_groups || [];
                    frm._permitted_sales_persons = d.sales_persons || [];
                }
            });
        }

        // Show "Create Address" button for Lead quotations without address
        if (frm.doc.quotation_to === "Lead" && frm.doc.party_name && !frm.doc.customer_address) {
            frm.add_custom_button(__("Create Address"), function () {
                show_create_address_dialog(frm);
            });
            // Make it stand out
            frm.change_custom_button_type(__("Create Address"), null, "primary");
        }

        // Toggle discount fields based on type selection
        toggle_discount_fields(frm);
        toggle_apply_discount_button(frm);

        // Mutual exclusion: Discount & Incentive vs Additional Discount
        enforce_discount_mutual_exclusion(frm);

        // Toggle incentive fields based on type selection
        toggle_incentive_fields(frm);
        toggle_apply_incentive_button(frm);
        toggle_incentive_readonly(frm);

        // Show Apply Incentive button instantly on input (not just on blur)
        setup_incentive_input_listener(frm);

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
            "custom_finance_",          // from Item Price / Brand
            "custom_transport_",        // from Item Price (processing)
            "custom_customs_",          // from Item Price
            "std_margin_per",           // from Item Price
            // Calculated value fields
            "shipping",                 // calculated from shipping_per
            "custom_finance_value",
            "custom_transport_value",
            "reward",
            // custom_incentive_ is toggled dynamically by toggle_incentive_readonly()
            "custom_incentive_value",
            "custom_markup_value",
            "custom_cogs",
            "custom_total_",
            "custom_customs_value",
            "custom_selling_price",
            "custom_margin_",
            "custom_margin_value",
            // custom_special_rate (label "Selling Price", per-unit) is now
            // user-editable — see the handler below which back-solves the
            // markup % so every derived field cascades correctly.
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

        // Hide ERPNext's native "Update Items" button on Quotation.
        // ERPNext adds this natively in versions newer than 15.95.2 —
        // Avientek policy requires cancel+amend for submitted quote
        // edits, so we strip the button out. Runs both immediately and
        // again on the next tick so it catches whether ERPNext's refresh
        // handler ran before or after ours.
        var _strip_update_items = function () {
            try { frm.remove_custom_button(__("Update Items")); } catch (e) {}
        };
        _strip_update_items();
        setTimeout(_strip_update_items, 0);
        setTimeout(_strip_update_items, 300);
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

    items_add(frm, cdt, cdn) {
        // When a row is duplicated, all fields are copied but totals aren't updated.
        // Recalculate the new row and update doc totals.
        let row = locals[cdt][cdn];
        if (row.custom_special_price) {
            calculate_all_preview(frm, cdt, cdn);
        }
        update_doc_totals_preview(frm);
    },

    items_remove(frm) {
        update_doc_totals_preview(frm);
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
        update_doc_totals_preview(frm);
        let row = locals[cdt][cdn];
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
    },

    qty(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        update_doc_totals_preview(frm);
        let row = locals[cdt][cdn];
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
    },

    shipping_per(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // Enforce minimum shipping % from Item Price (air/sea)
        if (frm.doc.custom_shipment_and_margin && frm.doc.custom_shipment_and_margin.length) {
            const ship_row = frm.doc.custom_shipment_and_margin[0];
            const mode = row.custom_shipping_mode || frm.doc.custom_shipping_mode;
            let min_shipping = 0;
            if (mode === "Air") min_shipping = flt(ship_row.ship_air);
            else if (mode === "Sea") min_shipping = flt(ship_row.ship_sea);

            if (min_shipping && flt(row.shipping_per) < min_shipping) {
                frappe.msgprint({
                    title: __('Minimum Shipping %'),
                    message: __('Shipping (%) cannot be less than {0}% (from Item Price). Resetting to minimum.', [min_shipping]),
                    indicator: 'orange'
                });
                frappe.model.set_value(cdt, cdn, "shipping_per", min_shipping);
                return;
            }
        }

        calculate_all_preview(frm, cdt, cdn);
        update_doc_totals_preview(frm);
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
    },

    reward_per(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        update_doc_totals_preview(frm);
    },

    custom_incentive_(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        update_doc_totals_preview(frm);
        let row = locals[cdt][cdn];
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
        // When "Distributed Manually", sync parent incentive fields from item totals
        sync_parent_incentive_from_items(frm);
    },

    custom_markup_(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        update_doc_totals_preview(frm);
        sync_shipment_margin_percent(frm, cdt, cdn);
        let row = locals[cdt][cdn];
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
    },

    // "Selling Price" (custom_special_rate, label "Selling Price") is the
    // PER-UNIT rate. When the user types a new per-unit price, we compute
    // the new line total (rate * qty), then back-solve the markup % that
    // reproduces it against the current COGS. Every derived field cascades:
    // Markup %, Markup Value, Margin %, Margin Value, Selling Amount, line
    // Total, and the standard ERPNext rate / amount / net_* pairs so taxes
    // + parent totals recompute. The same markup % is written so the server
    // calc_item_totals reproduces the same number on save.
    //
    // calculate_all_preview() writes custom_special_rate via direct row
    // assignment (not set_value), so internal cascades don't retrigger this
    // handler — only actual user edits fire it.
    custom_special_rate(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row) return;
        let qty = flt(row.qty) || 1;
        let cogs = flt(row.custom_cogs) || 0;
        let per_unit_selling = flt(row.custom_special_rate) || 0;
        if (per_unit_selling <= 0) return;

        let selling_price = per_unit_selling * qty;

        // Back-solve: markup on COGS such that cogs + markup == selling_price
        let markup_value = selling_price - cogs;
        let markup_percent = cogs > 0 ? (markup_value / cogs) * 100 : 0;

        // Margin is on selling price
        let margin_value = markup_value;
        let margin_percent = selling_price > 0 ? (margin_value / selling_price) * 100 : 0;

        let conversion_rate = flt(frm.doc.conversion_rate) || 1;

        // Direct row assignment so we don't bounce back into this handler
        row.custom_markup_value  = markup_value;
        row.custom_markup_       = markup_percent;
        row.custom_margin_value  = margin_value;
        row.custom_margin_       = margin_percent;
        row.custom_total_        = selling_price;
        row.custom_selling_price = selling_price;

        row.price_list_rate       = per_unit_selling;
        row.base_price_list_rate  = flt(per_unit_selling * conversion_rate);
        row.rate                  = per_unit_selling;
        row.base_rate             = flt(per_unit_selling * conversion_rate);
        row.net_rate              = per_unit_selling;
        row.base_net_rate         = flt(per_unit_selling * conversion_rate);
        row.amount                = selling_price;
        row.base_amount           = flt(selling_price * conversion_rate);
        row.net_amount            = selling_price;
        row.base_net_amount       = flt(selling_price * conversion_rate);

        frm.refresh_field("items");
        update_doc_totals_preview(frm);
        sync_shipment_margin_percent(frm, cdt, cdn);

        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }
    },

    custom_customs_(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        update_doc_totals_preview(frm);
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
        update_doc_totals_preview(frm);
    },

    custom_transport_(frm, cdt, cdn) {
        calculate_all_preview(frm, cdt, cdn);
        update_doc_totals_preview(frm);
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

    let conversion_rate = flt(frm.doc.conversion_rate) || 1;

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

    // Set ALL standard ERPNext rate/amount fields so that when ERPNext's
    // standard calculate_taxes_and_totals runs, it uses our selling price
    // instead of resetting to the original price_list_rate.
    row.price_list_rate       = per_unit_selling;
    row.base_price_list_rate  = flt(per_unit_selling * conversion_rate);
    row.rate                  = per_unit_selling;
    row.base_rate             = flt(per_unit_selling * conversion_rate);
    row.net_rate              = per_unit_selling;
    row.base_net_rate         = flt(per_unit_selling * conversion_rate);
    row.amount                = selling_price;
    row.base_amount           = flt(selling_price * conversion_rate);
    row.net_amount            = selling_price;
    row.base_net_amount       = flt(selling_price * conversion_rate);

    frm.refresh_field("items");
}


/**
 * Instant parent-level totals recalculation (mirrors server recalc_doc_totals).
 * Call after modifying multiple item rows to update summary fields.
 */
function update_doc_totals_preview(frm) {
    let totals = { shipping: 0, finance: 0, transport: 0, reward: 0,
                   incentive: 0, customs: 0, cost: 0, selling: 0, buying: 0 };

    (frm.doc.items || []).forEach(row => {
        totals.shipping  += flt(row.shipping);
        totals.finance   += flt(row.custom_finance_value);
        totals.transport += flt(row.custom_transport_value);
        totals.reward    += flt(row.reward);
        totals.incentive += flt(row.custom_incentive_value);
        totals.customs   += flt(row.custom_customs_value);
        totals.cost      += flt(row.custom_cogs);
        totals.selling   += flt(row.custom_selling_price);
        totals.buying    += flt(row.custom_special_price) * (flt(row.qty) || 1);
    });

    // Account for ERPNext's Additional Discount in margin and grand_total.
    // Use percentage as primary (server always derives from percentage).
    // Fall back to amount if only amount is set.
    let addl_discount = 0;
    if (flt(frm.doc.additional_discount_percentage) > 0) {
        addl_discount = flt(totals.selling * flt(frm.doc.additional_discount_percentage) / 100, 4);
    } else if (flt(frm.doc.discount_amount) > 0) {
        addl_discount = flt(frm.doc.discount_amount);
    }

    let effective_selling = flt(totals.selling - addl_discount, 4);
    let margin = effective_selling - totals.cost;
    let margin_pct = effective_selling ? (margin / effective_selling) * 100 : 0;

    frm.doc.custom_total_shipping_new       = flt(totals.shipping, 4);
    frm.doc.custom_total_finance_new        = flt(totals.finance, 4);
    frm.doc.custom_total_transport_new      = flt(totals.transport, 4);
    frm.doc.custom_total_reward_new         = flt(totals.reward, 4);
    frm.doc.custom_total_incentive_new      = flt(totals.incentive, 4);
    frm.doc.custom_total_customs_new        = flt(totals.customs, 4);
    frm.doc.custom_total_margin_new         = flt(margin, 4);
    frm.doc.custom_total_margin_percent_new = flt(margin_pct, 4);
    frm.doc.custom_total_cost_new           = flt(totals.cost, 4);
    frm.doc.custom_total_selling_new        = flt(effective_selling, 4);
    frm.doc.custom_total_buying_price       = flt(totals.buying, 4);

    // Standard ERPNext total fields (below items table)
    let total_qty = 0;
    (frm.doc.items || []).forEach(row => {
        total_qty += flt(row.qty);
    });
    let conversion_rate = flt(frm.doc.conversion_rate) || 1;
    frm.doc.total_qty    = flt(total_qty, 4);
    frm.doc.total        = flt(totals.selling, 4);
    frm.doc.net_total    = flt(totals.selling, 4);
    frm.doc.base_total   = flt(totals.selling * conversion_rate, 4);
    frm.doc.base_net_total = flt(totals.selling * conversion_rate, 4);
    // Recalculate taxes from the Taxes table (mirror server-side logic)
    let net_after_discount = flt(effective_selling, 4);
    let total_taxes = 0;
    let taxes = frm.doc.taxes || [];
    for (let i = 0; i < taxes.length; i++) {
        let tax_row = taxes[i];
        if (tax_row.charge_type === "On Net Total") {
            tax_row.tax_amount = flt(flt(tax_row.rate) * net_after_discount / 100, 4);
        } else if (tax_row.charge_type === "On Previous Row Total" && tax_row.row_id) {
            let prev_idx = cint(tax_row.row_id) - 1;
            if (prev_idx >= 0 && prev_idx < taxes.length) {
                tax_row.tax_amount = flt(flt(tax_row.rate) * flt(taxes[prev_idx].total) / 100, 4);
            }
        } else if (tax_row.charge_type === "On Previous Row Amount" && tax_row.row_id) {
            let prev_idx = cint(tax_row.row_id) - 1;
            if (prev_idx >= 0 && prev_idx < taxes.length) {
                tax_row.tax_amount = flt(flt(tax_row.rate) * flt(taxes[prev_idx].tax_amount) / 100, 4);
            }
        }
        // "Actual" charge_type: keep tax_amount as-is
        tax_row.base_tax_amount = flt(tax_row.tax_amount * conversion_rate, 4);
        let running_tax_sum = 0;
        for (let j = 0; j <= i; j++) { running_tax_sum += flt(taxes[j].tax_amount); }
        tax_row.total = flt(net_after_discount + running_tax_sum, 4);
        tax_row.base_total = flt(tax_row.total * conversion_rate, 4);
        total_taxes += flt(tax_row.tax_amount);
    }
    frm.doc.total_taxes_and_charges = flt(total_taxes, 4);
    frm.doc.base_total_taxes_and_charges = flt(total_taxes * conversion_rate, 4);

    frm.doc.grand_total  = flt(net_after_discount + total_taxes, 4);
    frm.doc.base_grand_total = flt(frm.doc.grand_total * conversion_rate, 4);
    frm.doc.rounded_total = Math.round(frm.doc.grand_total);
    frm.doc.base_rounded_total = Math.round(frm.doc.base_grand_total);

    // Sync Additional Discount Amount so ERPNext's calculate_taxes_and_totals
    // doesn't overwrite grand_total with stale values.
    frm.doc.discount_amount = flt(addl_discount, 4);
    frm.doc.base_discount_amount = flt(flt(frm.doc.discount_amount) * conversion_rate, 4);

    // Sync item-level net_rate / net_amount / base_* fields
    let item_amount_sum = flt(totals.selling);
    (frm.doc.items || []).forEach(row => {
        let qty = flt(row.qty) || 1;
        let rate = flt(row.rate);
        let amount = flt(row.amount);
        let selling = flt(row.custom_selling_price);
        let item_addl_disc = (addl_discount && totals.selling)
            ? flt(addl_discount * selling / totals.selling, 4) : 0;
        row.custom_addl_discount_amount = item_addl_disc;
        let net_amount_val = flt(amount - item_addl_disc, 4);
        let net_rate_val = qty ? flt(net_amount_val / qty, 4) : 0;

        // Recalculate per-item margin including additional discount
        if (item_addl_disc > 0) {
            let effective_selling = flt(selling - item_addl_disc, 4);
            let item_cost = flt(row.custom_cogs);
            row.custom_margin_value = flt(effective_selling - item_cost, 4);
            row.custom_margin_ = effective_selling
                ? flt((row.custom_margin_value / effective_selling) * 100, 4) : 0;
        }

        row.net_rate       = net_rate_val;
        row.net_amount     = net_amount_val;
        row.base_rate      = flt(rate * conversion_rate, 4);
        row.base_amount    = flt(amount * conversion_rate, 4);
        row.base_net_rate  = flt(net_rate_val * conversion_rate, 4);
        row.base_net_amount = flt(net_amount_val * conversion_rate, 4);
    });

    // ── Rebuild Brand Summary table (instant preview) ──
    rebuild_brand_summary_preview(frm, addl_discount);

    // ── Recalculate Total Margin from Brand Summary ──
    // Total Margin % = SUM of each brand's Margin (%) from Brand Summary table
    let bs_margin = 0;
    let bs_margin_pct_sum = 0;
    (frm.doc.custom_quotation_brand_summary || []).forEach(row => {
        bs_margin += flt(row.margin);
        bs_margin_pct_sum += flt(row.margin_percent);
    });
    if (bs_margin_pct_sum) {
        frm.doc.custom_total_margin_new         = flt(bs_margin, 4);
        frm.doc.custom_total_margin_percent_new = flt(bs_margin_pct_sum, 4);
    }

    frm.refresh_fields();

    // Force-refresh key total fields that may not update with refresh_fields()
    ["custom_total_margin_new", "custom_total_margin_percent_new",
     "custom_total_selling_new", "custom_total_cost_new", "custom_total_buying_price",
     "custom_total_shipping_new", "custom_total_finance_new", "custom_total_transport_new",
     "custom_total_reward_new", "custom_total_incentive_new", "custom_total_customs_new"
    ].forEach(fn => frm.refresh_field(fn));
}


/**
 * Rebuild Brand Summary child table in JS preview.
 * Mirrors server-side rebuild_brand_summary() + addl discount distribution.
 */
function rebuild_brand_summary_preview(frm, addl_discount) {
    let buckets = {};
    (frm.doc.items || []).forEach(row => {
        let b = row.brand || "Unbranded";
        if (!buckets[b]) {
            buckets[b] = {
                shipping: 0, shipping_pct: 0,
                finance: 0, finance_pct: 0,
                processing: 0, processing_pct: 0,
                reward: 0, reward_pct: 0,
                incentive: 0, incentive_pct: 0,
                customs: 0, customs_pct: 0,
                buying: 0, cost: 0, selling: 0, cnt: 0,
            };
        }
        let bk = buckets[b];
        let qty = Math.max(cint(row.qty), 1);
        bk.shipping     += flt(row.shipping);
        bk.shipping_pct += flt(row.shipping_per);
        bk.finance      += flt(row.custom_finance_value);
        bk.finance_pct  += flt(row.custom_finance_);
        bk.processing   += flt(row.custom_transport_value);
        bk.processing_pct += flt(row.custom_transport_);
        bk.reward       += flt(row.reward);
        bk.reward_pct   += flt(row.reward_per);
        bk.incentive    += flt(row.custom_incentive_value);
        bk.incentive_pct += flt(row.custom_incentive_);
        bk.customs      += flt(row.custom_customs_value);
        bk.customs_pct  += flt(row.custom_customs_);
        bk.buying       += flt(flt(row.custom_special_price) * qty, 4);
        bk.cost         += flt(row.custom_cogs);
        bk.selling      += flt(row.custom_selling_price);
        bk.cnt          += 1;
    });

    let total_selling = Object.values(buckets).reduce((s, b) => s + b.selling, 0);

    frm.doc.custom_quotation_brand_summary = [];
    Object.keys(buckets).forEach(brand => {
        let d = buckets[brand];
        let n = d.cnt || 1;
        let ts = d.selling;
        let tc = d.cost;

        // Distribute addl discount pro-rata
        let brand_addl = (addl_discount > 0 && total_selling > 0)
            ? flt(addl_discount * ts / total_selling, 4) : 0;
        let eff_ts = flt(ts - brand_addl, 4);
        let margin_pct = eff_ts ? flt((eff_ts - tc) / eff_ts * 100, 4) : 0;

        let row = frm.add_child("custom_quotation_brand_summary");
        row.brand            = brand;
        row.buying_price     = flt(d.buying, 4);
        row.shipping         = flt(d.shipping, 4);
        row.shipping_percent = flt(d.shipping_pct / n, 4);
        row.finance          = flt(d.finance, 4);
        row.finance_percent  = flt(d.finance_pct / n, 4);
        row.processing       = flt(d.processing, 4);
        row.processing_percent = flt(d.processing_pct / n, 4);
        row.reward           = flt(d.reward, 4);
        row.reward_percent   = flt(d.reward_pct / n, 4);
        row.incentive        = flt(d.incentive, 4);
        row.incentive_percent = flt(d.incentive_pct / n, 4);
        row.customs          = flt(d.customs, 4);
        row.customs_         = flt(d.customs_pct / n, 4);
        row.total_cost       = flt(tc, 4);
        row.total_selling    = flt(eff_ts, 4);
        // Clamp margin to prevent decimal(21,9) overflow on save
        var raw_margin = flt(eff_ts - tc, 4);
        row.margin           = Math.max(-999999999999, Math.min(999999999999, raw_margin));
        row.margin_percent   = margin_pct;
    });
}


/**
 * Single server call to load all item defaults when item_code is selected.
 * Replaces the old rate_calculation + update_rates nested async calls.
 */
/**
 * Show dialog to create a new Address for a Lead directly from Quotation.
 */
function show_create_address_dialog(frm) {
    let lead_name = frm.doc.party_name;
    if (!lead_name) {
        frappe.msgprint(__("Please select a Lead first."));
        return;
    }

    let d = new frappe.ui.Dialog({
        title: __("Create Address for {0}", [lead_name]),
        fields: [
            { fieldname: "address_title", fieldtype: "Data", label: __("Address Title"), reqd: 1,
              default: frm.doc.title || lead_name },
            { fieldname: "address_type", fieldtype: "Select", label: __("Address Type"),
              options: "Billing\nShipping\nOffice\nPersonal\nPlant\nPostal\nShop\nSubsidiary\nWarehouse\nOther",
              default: "Billing", reqd: 1 },
            { fieldtype: "Section Break" },
            { fieldname: "address_line1", fieldtype: "Data", label: __("Address Line 1"), reqd: 1 },
            { fieldname: "address_line2", fieldtype: "Data", label: __("Address Line 2") },
            { fieldtype: "Column Break" },
            { fieldname: "city", fieldtype: "Data", label: __("City"), reqd: 1 },
            { fieldname: "state", fieldtype: "Data", label: __("State") },
            { fieldtype: "Section Break" },
            { fieldname: "country", fieldtype: "Link", label: __("Country"), options: "Country", reqd: 1 },
            { fieldname: "pincode", fieldtype: "Data", label: __("Postal Code") },
            { fieldtype: "Column Break" },
            { fieldname: "phone", fieldtype: "Data", label: __("Phone") },
            { fieldname: "email_id", fieldtype: "Data", label: __("Email"), options: "Email" },
        ],
        primary_action_label: __("Create"),
        primary_action: function (values) {
            frappe.call({
                method: "frappe.client.insert",
                args: {
                    doc: {
                        doctype: "Address",
                        address_title: values.address_title,
                        address_type: values.address_type,
                        address_line1: values.address_line1,
                        address_line2: values.address_line2,
                        city: values.city,
                        state: values.state,
                        country: values.country,
                        pincode: values.pincode,
                        phone: values.phone,
                        email_id: values.email_id,
                        links: [{
                            link_doctype: "Lead",
                            link_name: lead_name,
                        }],
                    },
                },
                freeze: true,
                freeze_message: __("Creating Address..."),
                callback: function (r) {
                    if (r.message) {
                        d.hide();
                        frm.set_value("customer_address", r.message.name);
                        frappe.show_alert({
                            message: __("Address {0} created and linked to {1}", [r.message.name, lead_name]),
                            indicator: "green",
                        }, 5);
                    }
                },
            });
        },
    });
    d.show();
}


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
            let d = r.message;

            // No Item Price for this company — block selection and warn.
            // Per Sridhar 2026-04-29: at item selection time, if the item
            // is not on the company's Item Price List, show a popup
            // "Please update the Item Price List for this item." and do
            // not allow the row to keep that item — clearing item_code
            // forces the user to either pick a priced item or update the
            // price list before continuing.
            if (d.no_price_for_company) {
                frappe.msgprint({
                    title: __('No Item Price Found'),
                    message: __('No Item Price found for <b>{0}</b> in company <b>{1}</b> and price list <b>{2}</b>. Please update the Item Price List for this item.', [d.item_code, d.company, d.price_list]),
                    indicator: 'orange'
                });
                // Clear the item from the row so it can't be saved unpriced.
                frappe.model.set_value(cdt, cdn, 'item_code', '');
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
            update_doc_totals_preview(frm);

            // ERPNext's standard item_code handler also makes an async call
            // (get_item_details) that returns AFTER ours and resets
            // price_list_rate/rate/amount/grand_total to the raw Item Price.
            // frappe.after_ajax waits for ALL pending ajax calls to finish,
            // then we re-apply our calculated selling price values.
            frappe.after_ajax(() => {
                calculate_all_preview(frm, cdt, cdn);
                update_doc_totals_preview(frm);
                // Re-render item info HTML with updated Cl.Margin
                let updated_row = locals[cdt][cdn];
                if (updated_row && updated_row.item_code) {
                    refresh_item_info_html(frm, updated_row.item_code);
                }
            });
        }
    });
}


/**
 * Full calculation pipeline that mirrors server's run_calculation_pipeline.
 * Used by both before_save and calculate_taxes_and_totals override to
 * ensure live preview always matches server output.
 */
function run_full_calculation_preview(frm) {
    // 1) Recalculate all items from scratch (like server calc_item_totals)
    (frm.doc.items || []).forEach(row => {
        if (row.custom_special_price) {
            calculate_all_preview(frm, row.doctype, row.name);
        }
    });

    // 2) Distribute custom discount (like server distribute_discount_server)
    let custom_disc = flt(frm.doc.custom_discount_amount_value);
    if (custom_disc > 0) {
        let total_selling = 0;
        (frm.doc.items || []).forEach(row => {
            total_selling += flt(row.custom_selling_price);
        });
        if (total_selling > 0) {
            let conversion_rate = flt(frm.doc.conversion_rate) || 1;
            (frm.doc.items || []).forEach(row => {
                let selling = flt(row.custom_selling_price);
                let qty = flt(row.qty) || 1;
                let cogs = flt(row.custom_cogs);
                let share = selling / total_selling;
                let item_discount = flt(custom_disc * share, 4);
                let new_selling = Math.max(flt(selling - item_discount, 4), 0);
                let new_rate = flt(new_selling / qty, 4);
                let margin_val = Math.max(flt(new_selling - cogs, 4), 0);
                let margin_pct = new_selling ? flt(margin_val / new_selling * 100, 4) : 0;

                row.custom_discount_amount_value = flt(item_discount / qty, 4);
                row.custom_discount_amount_qty = item_discount;
                row.custom_selling_price = new_selling;
                row.custom_total_ = new_selling;
                row.custom_special_rate = new_rate;
                row.rate = new_rate;
                row.amount = new_selling;
                row.base_rate = flt(new_rate * conversion_rate);
                row.base_amount = flt(new_selling * conversion_rate);
                row.net_rate = new_rate;
                row.net_amount = new_selling;
                row.base_net_rate = flt(new_rate * conversion_rate);
                row.base_net_amount = flt(new_selling * conversion_rate);
                row.price_list_rate = new_rate;
                row.base_price_list_rate = flt(new_rate * conversion_rate);
                row.custom_margin_value = margin_val;
                row.custom_margin_ = margin_pct;
            });
        }
    }

    // 3) ERPNext's discount_amount handler sets percentage=0 before calling
    //    calculate_taxes_and_totals. Back-calculate percentage from amount.
    let ts = 0;
    (frm.doc.items || []).forEach(row => {
        ts += flt(row.custom_selling_price);
    });
    if (flt(frm.doc.additional_discount_percentage) === 0
        && flt(frm.doc.discount_amount) > 0 && ts) {
        frm.doc.additional_discount_percentage = flt(
            flt(frm.doc.discount_amount) / ts * 100, 4
        );
    }

    // 4) Update totals (like server recalc_doc_totals)
    update_doc_totals_preview(frm);
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
/**
 * Discount co-existence handler.
 *
 * Both Discount & Incentive and Additional Discount can work together.
 * One-directional auto-clear: entering Disc & Inc clears existing Addl Discount
 * (since item prices change, the old Addl Discount would be stale).
 * But entering Addl Discount works ON TOP of existing Disc & Inc (no clearing).
 *
 * @param {string} [source] - Which section triggered the call:
 *   "disc_inc" = Discount & Incentive changed
 *   "addl"     = Additional Discount changed
 *   undefined  = refresh / init
 */
function enforce_discount_mutual_exclusion(frm, source) {
    let has_disc_inc = flt(frm.doc.custom_discount_amount_value) > 0 || flt(frm.doc.custom_discount_) > 0;
    let has_addl = flt(frm.doc.additional_discount_percentage) > 0 || flt(frm.doc.discount_amount) > 0;

    // One-directional auto-clear: Disc & Inc changes invalidate Addl Discount
    // (because item selling prices change, the old addl discount % is stale)
    if (source === "disc_inc" && has_disc_inc && has_addl) {
        frm.doc.additional_discount_percentage = 0;
        frm.doc.discount_amount = 0;
        frm.doc.base_discount_amount = 0;
        (frm.doc.items || []).forEach(row => { row.custom_addl_discount_amount = 0; });
        frm.refresh_fields();
        frappe.show_alert({
            message: __("Additional Discount has been reset because Discount & Incentive was changed. You can re-enter it after applying the discount."),
            indicator: "orange"
        }, 7);
    }

    // Re-read current state (may have been cleared above)
    has_disc_inc = flt(frm.doc.custom_discount_amount_value) > 0 || flt(frm.doc.custom_discount_) > 0;
    has_addl = flt(frm.doc.additional_discount_percentage) > 0 || flt(frm.doc.discount_amount) > 0;

    // Both sections always remain editable — no locking
    frm.set_df_property("additional_discount_percentage", "read_only", 0);
    frm.set_df_property("discount_amount", "read_only", 0);
    frm.set_df_property("additional_discount_percentage", "description", "");
    frm.set_df_property("custom_discount_amount_value", "description", "");
    toggle_discount_fields(frm);

    // Show hint only when BOTH are actively set
    if (has_disc_inc && has_addl) {
        frm.set_df_property("additional_discount_percentage", "description",
            "<span style='color:green'>Applied on top of Discount &amp; Incentive</span>");
    }
}

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

/**
 * Toggle item-level incentive field editability based on distribution mode.
 * "Distributed Manually" → editable; all other modes → read-only.
 */
function toggle_incentive_readonly(frm) {
    let mode = frm.doc.custom_distribute_incentive_based_on || "Amount";
    let read_only = (mode === "Distributed Manually") ? 0 : 1;
    frm.fields_dict.items.grid.update_docfield_property("custom_incentive_", "read_only", read_only);
    frm.refresh_field("items");
}

/**
 * Setup real-time input listener on incentive fields so the Apply Incentive
 * button appears immediately as the user types, not just on blur.
 */
function setup_incentive_input_listener(frm) {
    if (frm._incentive_input_listener_set) return;
    frm._incentive_input_listener_set = true;

    // Listen for input events on the incentive percentage and amount fields
    ["custom_incentive_", "custom_incentive_amount"].forEach(fieldname => {
        let field = frm.fields_dict[fieldname];
        if (field && field.$input) {
            field.$input.on("input", function() {
                frm._incentive_applied = false;
                frm.set_df_property("custom_apply_incentive", "hidden", 0);
            });
        }
    });
}

/**
 * Re-apply discount proportionally across items after incentive recalculation.
 * This preserves the discount when incentive is applied/changed.
 */
function reapply_discount_preview(frm, discount_amount) {
    let items = frm.doc.items || [];
    if (!items.length || !discount_amount) return;

    // Read fresh total selling (after incentive recalc, before discount)
    let total_selling = 0;
    items.forEach(row => {
        total_selling += flt(row.custom_selling_price);
    });

    if (total_selling <= 0) return;

    items.forEach(row => {
        let selling = flt(row.custom_selling_price);
        let qty = flt(row.qty) || 1;
        let cogs = flt(row.custom_cogs);
        let conversion_rate = flt(frm.doc.conversion_rate) || 1;

        let share = total_selling ? (selling / total_selling) : 0;
        let item_discount = flt(discount_amount * share, 4);

        let new_selling = Math.max(selling - item_discount, 0);
        let new_rate = flt(new_selling / qty, 4);
        let new_margin_val = flt(new_selling - cogs, 4);
        let new_margin_pct = new_selling ? flt((new_margin_val / new_selling) * 100, 4) : 0;

        row.custom_discount_amount_value = flt(item_discount / qty, 4);
        row.custom_discount_amount_qty   = flt(item_discount, 4);
        row.custom_special_rate          = new_rate;
        row.custom_selling_price         = new_selling;
        row.custom_total_                = new_selling;
        row.price_list_rate              = new_rate;
        row.base_price_list_rate         = flt(new_rate * conversion_rate);
        row.rate                         = new_rate;
        row.base_rate                    = flt(new_rate * conversion_rate);
        row.net_rate                     = new_rate;
        row.amount                       = new_selling;
        row.base_amount                  = flt(new_selling * conversion_rate);
        row.net_amount                   = new_selling;
        row.base_net_amount              = flt(new_selling * conversion_rate);
        row.custom_margin_value          = new_margin_val;
        row.custom_margin_               = new_margin_pct;
    });

    frm.refresh_field("items");
}

/**
 * When distribution mode is "Distributed Manually", sync parent-level
 * incentive % and amount from the sum of item-level incentive values.
 */
function sync_parent_incentive_from_items(frm) {
    let mode = frm.doc.custom_distribute_incentive_based_on || "Amount";
    if (mode !== "Distributed Manually") return;

    let total_incentive = 0;
    let total_sp = 0;
    (frm.doc.items || []).forEach(row => {
        total_incentive += flt(row.custom_incentive_value);
        total_sp += flt(row.custom_special_price) * (flt(row.qty) || 1);
    });

    let pct = total_sp ? flt(total_incentive / total_sp * 100, 4) : 0;

    // Use direct assignment + refresh to avoid triggering normalize loop
    frm.doc.custom_incentive_amount = flt(total_incentive, 4);
    frm.doc.custom_incentive_ = pct;
    frm.refresh_field("custom_incentive_amount");
    frm.refresh_field("custom_incentive_");
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
            // Check all items with this code and pick the one with a margin value (or the first)
            let item_rows = (frm.doc.items || []).filter(row => row.item_code === item_code);
            let cal_margin = 0;
            for (let ir of item_rows) {
                if (flt(ir.custom_margin_)) { cal_margin = flt(ir.custom_margin_); break; }
            }
            r.message.cal_margin = cal_margin;

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
    // Jithin 2026-05-15 — pin the dialog's Currency formatting to the
    // quote's currency. First attempt used `options: <literal_code>`
    // (e.g., "INR") which Frappe's grid Currency formatter treats as a
    // fieldname reference, not a literal — so when no row column with
    // that name exists, it silently falls back to the system default
    // currency (AED on this site). Fix: embed `currency_code` as a
    // hidden column on every row carrying frm.doc.currency, then
    // point each Currency column's `options` at that column name.
    const doc_currency = frm.doc.currency || frappe.defaults.get_global_default("currency") || "AED";

    // Jithin 2026-05-15 (real-time Margin %) — capture each row's cost
    // components by name so we can recompute margin client-side as
    // the user changes Special Price. Mirrors the server-side formula
    // in avientek.events.quotation.update_special_price exactly.
    const cost_map = {};
    (frm.doc.items || []).forEach(row => {
        cost_map[row.name] = {
            std_price:     flt(row.custom_standard_price_),
            shipping_per:  flt(row.shipping_per),
            finance_per:   flt(row.custom_finance_),
            transport_per: flt(row.custom_transport_),
            reward_per:    flt(row.reward_per),
            incentive_per: flt(row.custom_incentive_),
            customs_per:   flt(row.custom_customs_),
            selling:       flt(row.custom_selling_price),
            qty:           Math.max(cint(row.qty), 1),
        };
    });

    let items = (frm.doc.items || []).map(row => ({
        name: row.name,
        item_code: row.item_code,
        qty: row.qty,
        custom_special_price: row.custom_special_price,
        custom_special_price_note: row.custom_special_price_note || "",
        custom_special_rate: row.custom_special_rate,
        custom_selling_price: row.custom_selling_price,
        custom_margin_: row.custom_margin_,
        currency_code: doc_currency,
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
                { fieldname: "currency_code", fieldtype: "Data", hidden: 1 },
                { fieldname: "item_code", fieldtype: "Data", label: __("Item Code"), in_list_view: 1, read_only: 1, columns: 2 },
                { fieldname: "qty", fieldtype: "Float", label: __("Qty"), in_list_view: 1, read_only: 1, columns: 1 },
                { fieldname: "custom_special_price", fieldtype: "Currency", options: "currency_code", label: __("Special Price"), in_list_view: 1, columns: 2 },
                { fieldname: "custom_special_price_note", fieldtype: "Data", label: __("Special Price Note"), in_list_view: 1, columns: 2 },
                { fieldname: "custom_special_rate", fieldtype: "Currency", options: "currency_code", label: __("Selling Price"), in_list_view: 1, read_only: 1, columns: 2 },
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

    // Jithin 2026-05-15 — live Margin % recompute when Special Price
    // changes. Mirrors avientek.events.quotation.update_special_price.
    function compute_margin_for_row(row) {
        const c = cost_map[row.name];
        if (!c) return null;
        const new_sp    = flt(row.custom_special_price);
        const qty       = c.qty;
        const shipping  = flt(c.shipping_per  * c.std_price / 100 * qty, 4);
        const finance   = flt(c.finance_per   * new_sp      / 100 * qty, 4);
        const transport = flt(c.transport_per * c.std_price / 100 * qty, 4);
        const reward    = flt(c.reward_per    * new_sp      / 100 * qty, 4);
        const base_amt  = flt(new_sp * qty + shipping + finance + transport + reward, 4);
        const incentive = flt(c.incentive_per * new_sp * qty / 100, 4);
        const cogs_pre  = flt(base_amt + incentive, 4);
        const customs   = flt(c.customs_per * cogs_pre / 100, 4);
        const cogs      = flt(cogs_pre + customs, 4);
        const selling   = c.selling;
        const margin_val = flt(selling - cogs, 4);
        const margin_pct = selling ? flt(margin_val / selling * 100, 4) : 0;
        return { margin_pct, cogs };
    }

    d.show();

    // Refresh the visible Margin % cell when user edits Special Price.
    // DOM-level binding is the most reliable cross-version pattern for
    // Dialog Tables (the field-def `change` callback doesn't fire on
    // dialog tables in v15 the way it does on form child grids).
    $(d.$wrapper).on("change input keyup", '[data-fieldname="custom_special_price"] input', function () {
        const $row = $(this).closest(".grid-row");
        const idx_attr = $row.attr("data-idx");
        if (!idx_attr) return;
        const idx = parseInt(idx_attr, 10) - 1;
        const data = d.fields_dict.items.df.data || [];
        const row = data[idx];
        if (!row) return;

        // Sync the typed value into the row data, stripping thousand separators.
        const raw = $(this).val();
        if (raw !== undefined) {
            row.custom_special_price = flt((raw + "").replace(/,/g, ""));
        }

        const result = compute_margin_for_row(row);
        if (!result) return;
        row.custom_margin_ = result.margin_pct;

        // Update the read-only Margin % cell display.
        const $cell = $row.find('[data-fieldname="custom_margin_"]').first();
        if ($cell.length) {
            const display = flt(result.margin_pct, 2) + " %";
            const $static = $cell.find(".static-area, .ellipsis").first();
            if ($static.length) {
                $static.text(display);
            } else {
                $cell.text(display);
            }
        }
    });

    // Widen dialog beyond extra-large default for better table readability
    d.$wrapper.find(".modal-dialog").css("max-width", "1100px");
}


// Sridhar 2026-05-27 (Probability BRD, Jithin/FM approved): on a submitted
// Quotation, when sales lowers `probabilities` from >=75% to <75%, pop a
// dialog for a mandatory "Reason for Change". Reason is written to the
// Custom Field probability_change_reason; on save the server validator
// reads it, writes an audit Comment, and clears the field.
//
// Sridhar 2026-05-28 (baseline bug fix): trigger now compares the new
// value against `submitted_probability` (frozen at submit time) instead
// of the last saved value. Previous version let post-refresh edits slip
// through after the first downgrade because the new low value became
// the baseline. Per BRD: "original probability at the time of submission"
// is the eternal baseline.
//
// If user cancels the popup, the probabilities field is visually reverted
// to the pre-change value so the form matches the persisted state.
frappe.ui.form.on('Quotation', {
    probabilities(frm) {
        // Only intercept on submitted docs
        if (frm.doc.docstatus !== 1) return;

        // BASELINE = the probability captured at submit time (never changes).
        // Falls back to the last-saved snapshot for legacy docs that don't
        // have submitted_probability backfilled yet.
        const submitted = (frm.doc.submitted_probability || '').trim();
        const oldRaw = submitted || frm.__last_probabilities_snapshot || '';
        const newRaw = (frm.doc.probabilities || '');

        const pct = (v) => {
            const n = parseInt(String(v || '').replace('%', '').trim(), 10);
            return isNaN(n) ? 0 : n;
        };
        const oldPct = pct(oldRaw);
        const newPct = pct(newRaw);

        // Trigger condition: submitted >= 75% AND new < 75% AND value actually
        // changed. Per BRD, originally-low quotes (submitted <75%) get all
        // post-submit edits for free.
        if (!(oldPct >= 75 && newPct < 75 && oldRaw !== newRaw)) {
            frm.__last_probabilities_snapshot = newRaw;
            return;
        }

        // Guard against re-triggering during the dialog flow
        if (frm.__probability_popup_open) return;
        frm.__probability_popup_open = true;

        const d = new frappe.ui.Dialog({
            title: __('Probability Downgrade Approval'),
            fields: [
                {
                    fieldname: 'banner',
                    fieldtype: 'HTML',
                    options: `<div style="padding:10px 14px;margin-bottom:12px;
                                 background:#fff3cd;border:1px solid #ffe69c;
                                 border-radius:6px;color:#664d03;">
                        <b>${__('Approval required')}</b><br>
                        ${__('Downgrading probability from')} <b>${frappe.utils.escape_html(oldRaw)}</b>
                        ${__('to')} <b>${frappe.utils.escape_html(newRaw)}</b>
                        ${__('on a submitted Quotation requires management approval. Please enter a reason — it will be logged on the Quotation and shown to the approver.')}
                      </div>`,
                },
                {
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    label: __('Reason for Change'),
                    reqd: 1,
                    description: __('Be specific so the approver understands why the deal probability dropped.'),
                },
            ],
            primary_action_label: __('Send for Approval'),
            primary_action(values) {
                const reason = (values.reason || '').trim();
                if (!reason) {
                    frappe.throw(__('Reason is required'));
                    return;
                }
                d.hide();
                frm.__probability_popup_open = false;

                // Sridhar 2026-05-29 (BRD-faithful): the server captures
                // the request in pending_probability_* fields without
                // touching `probabilities` itself. We revert the form
                // value to oldRaw immediately (BRD: "field should
                // visually revert to its previous high value until
                // approval is officially granted") and reload to pull
                // the pending state for the approver banner.
                frappe.call({
                    method: 'avientek.events.quotation.submit_probability_change',
                    args: {
                        quotation_name: frm.doc.name,
                        new_probability: newRaw,
                        reason: reason,
                    },
                    freeze: true,
                    freeze_message: __('Submitting probability change for approval...'),
                }).then((r) => {
                    if (!(r && r.message && r.message.ok)) {
                        frappe.show_alert({
                            message: __('Unexpected response from server.'),
                            indicator: 'red',
                        });
                        return;
                    }
                    // BRD visual revert: restore old high value in the
                    // form before reload, so there's no flicker showing
                    // the requested low value.
                    frm.doc.probabilities = oldRaw;
                    frm.refresh_field('probabilities');
                    frm.__last_probabilities_snapshot = oldRaw;

                    frm.reload_doc().then(() => {
                        if (r.message.no_approval_needed) {
                            frappe.show_alert({
                                message: __('Probability updated.'),
                                indicator: 'green',
                            });
                        } else {
                            frappe.show_alert({
                                message: __('Probability change submitted. Awaiting approver. Field reverted to current value until approved.'),
                                indicator: 'orange',
                            });
                        }
                    });
                }).catch(() => {
                    // Revert visually so user can retry
                    frm.doc.probabilities = oldRaw;
                    frm.refresh_field('probabilities');
                    frm.__last_probabilities_snapshot = oldRaw;
                });
            },
            secondary_action_label: __('Cancel'),
            secondary_action() {
                // Revert the field visually so it matches the persisted state
                frm.doc.probabilities = oldRaw;
                frm.refresh_field('probabilities');
                frm.__last_probabilities_snapshot = oldRaw;
                d.hide();
                frm.__probability_popup_open = false;
            },
        });
        d.show();
    },

    refresh(frm) {
        // Capture baseline once on load so the change handler can detect
        // downgrades from the submitted snapshot.
        if (frm.doc.docstatus === 1 && frm.__last_probabilities_snapshot === undefined) {
            frm.__last_probabilities_snapshot = frm.doc.probabilities || '';
        }

        // Sridhar 2026-05-29 (BRD): show pending probability change banner
        // + Approve/Reject buttons for users with the approver role
        // (quote_l2_approver_roles via Avientek Settings).
        _render_pending_probability_ui(frm);
    },
});


function _render_pending_probability_ui(frm) {
    if (frm.is_new() || frm.doc.docstatus !== 1) return;
    if ((frm.doc.pending_probability_status || '') !== 'Pending') return;

    const oldVal = frm.doc.probabilities || '';
    const newVal = frm.doc.pending_probability_value || '';
    const reason = frm.doc.pending_probability_reason || '';
    const requestedBy = frm.doc.pending_probability_requested_by || '(unknown)';
    const requestedAt = frm.doc.pending_probability_requested_at || '';

    // Orange dashboard banner. set_headline replaces any previous one
    // so this stays the dominant message until cleared on next refresh.
    frm.dashboard.set_headline(
        __(
            '<b>Pending Probability Change</b><br>'
            + 'Requested: <b>{0}</b> &rarr; <b>{1}</b><br>'
            + 'By <b>{2}</b> at <b>{3}</b><br>'
            + 'Reason: {4}',
            [
                frappe.utils.escape_html(oldVal),
                frappe.utils.escape_html(newVal),
                frappe.utils.escape_html(requestedBy),
                frappe.utils.escape_html(String(requestedAt).slice(0, 16).replace('T', ' ')),
                frappe.utils.escape_html(reason).replace(/\n/g, '<br>'),
            ]
        ),
        'orange'
    );

    // Approve/Reject buttons only for users with the configured role.
    frappe.call({
        method: 'avientek.events.quotation.can_approve_probability_change',
        args: { quotation_name: frm.doc.name },
    }).then((r) => {
        const can = r && r.message;
        // Surface diagnostic in console — helps Sridhar see WHY buttons
        // didn't appear for a given user.
        console.log("[avk] can approve probability change:", can,
                    "as user:", frappe.session.user);
        if (!can) return;

        // Sridhar 2026-05-29: revert to a single "Probability" dropdown
        // with Approve / Reject inside — less visually intrusive than two
        // big standalone colored buttons.
        frm.add_custom_button(__('Approve'), () => {
            frappe.confirm(
                __('Approve change of probability from {0} to {1}?', [oldVal, newVal]),
                () => {
                    frappe.call({
                        method: 'avientek.events.quotation.approve_probability_change',
                        args: { quotation_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Approving...'),
                    }).then((rr) => {
                        if (rr && rr.message && rr.message.ok) {
                            frm.reload_doc().then(() => {
                                frappe.show_alert({
                                    message: __('Probability change approved.'),
                                    indicator: 'green',
                                });
                            });
                        }
                    });
                }
            );
        }, __('Probability'));

        frm.add_custom_button(__('Reject'), () => {
            const rd = new frappe.ui.Dialog({
                title: __('Reject Probability Change'),
                fields: [
                    {
                        fieldname: 'rejection_reason',
                        fieldtype: 'Small Text',
                        label: __('Rejection Reason'),
                        reqd: 1,
                        description: __('Explain why this downgrade is not approved.'),
                    },
                ],
                primary_action_label: __('Reject'),
                primary_action(v) {
                    const rr = (v.rejection_reason || '').trim();
                    if (!rr) { frappe.throw(__('Rejection reason is required')); return; }
                    rd.hide();
                    frappe.call({
                        method: 'avientek.events.quotation.reject_probability_change',
                        args: { quotation_name: frm.doc.name, rejection_reason: rr },
                        freeze: true,
                        freeze_message: __('Rejecting...'),
                    }).then((rrx) => {
                        if (rrx && rrx.message && rrx.message.ok) {
                            frm.reload_doc().then(() => {
                                frappe.show_alert({
                                    message: __('Probability change rejected.'),
                                    indicator: 'red',
                                });
                            });
                        }
                    });
                },
            });
            rd.show();
        }, __('Probability'));
    });
}
