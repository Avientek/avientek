// Sridhar/Rahul 2026-06-10/11: when a PI is created from a PR and the
// user then changes posting_date / conversion_rate / currency / bill_date
// in the UI, ERPNext's posting_date trigger fires set_exchange_rate which
// re-derives each item's rate using the new PLE + cached fields —
// producing nonsense numbers in the grid (sometimes negative; e.g. row 1
// $-164.00, row 2 $570.00 from a PR where both rows were $665.00).
//
// Production-ready design:
//
//   1. Restore ONLY doc-currency fields (rate, price_list_rate,
//      discount_*, margin_*). The earlier draft of this fix also
//      restored base_rate / base_price_list_rate / net_rate /
//      base_net_rate — those were computed at PR's PLE; copying them
//      at a different PI PLE creates an inconsistent state that
//      ERPNext resolves by deriving `rate = base_rate /
//      current_conversion_rate`, silently overriding our USD-side
//      lock. Row 1 ended at $664.94 instead of $665.00; row 2 went
//      to $0.00 from a net_rate clamp. The server _PR_PRICING_FIELDS
//      list was trimmed in lockstep so both server + client agree.
//
//   2. Use DIRECT assignment (`it[k] = v`), not frappe.model.set_value.
//      set_value fires per-field handlers in turn — setting rate
//      triggers a recalc, then setting price_list_rate triggers
//      another, then discount_amount triggers another, each cascading
//      and possibly undoing the prior. Direct assignment writes the
//      whole locked dict cleanly, then ONE calculate_taxes_and_totals
//      derives every base_* / net_* / amount field coherently from the
//      restored doc-currency values + the PI's current
//      conversion_rate.
//
//   3. Debounce 150ms: posting_date can cascade into conversion_rate
//      and plc_conversion_rate; coalesce all into one network round
//      trip per user action.
//
//   4. Mark dirty after a restore so the save button reflects the
//      change and the validate hook picks up the corrected items.
function _avtk_restore_pr_locked_pricing(frm) {
    if (!frm || !frm.doc || frm.doc.is_return) return;
    if (!(frm.doc.items || []).length) return;

    const pr_details = (frm.doc.items || [])
        .map(it => it.pr_detail)
        .filter(Boolean);
    if (!pr_details.length) return;

    if (frm._avtk_pr_lock_pending) {
        clearTimeout(frm._avtk_pr_lock_pending);
    }
    frm._avtk_pr_lock_pending = setTimeout(function () {
        frm._avtk_pr_lock_pending = null;

        // Re-entrancy guard: calculate_taxes_and_totals at the end of
        // a restore can itself fire follow-up triggers (e.g. base_*
        // updates re-emit conversion_rate). If we don't guard, restore
        // → set rate → fires its handler → triggers conversion_rate-
        // like cascade → schedules another restore → loop. The flag
        // gates re-entry within this user action.
        if (frm._avtk_pr_lock_restoring) return;

        frappe.call({
            method: "avientek.events.purchase_invoice.get_pr_locked_pricing",
            args: { pr_details: pr_details },
            callback: function (r) {
                const pricing = (r && r.message) || {};
                if (!Object.keys(pricing).length) return;

                let changed = false;
                frm._avtk_pr_lock_restoring = true;
                try {
                    (frm.doc.items || []).forEach(function (it) {
                        const lock = pricing[it.pr_detail];
                        if (!lock) return;
                        Object.keys(lock).forEach(function (k) {
                            const v = lock[k];
                            if (v == null) return;
                            // Number-tolerant compare (Frappe sometimes
                            // returns strings for numeric fields).
                            const cur = it[k];
                            const same =
                                cur === v ||
                                (cur != null && v != null &&
                                 Number(cur) === Number(v));
                            if (!same) {
                                it[k] = v;       // direct assign — no handler
                                changed = true;
                            }
                        });
                    });
                } finally {
                    // Release the guard BEFORE calculate_taxes_and_totals
                    // so that the user's next trigger (a fresh change)
                    // can run a fresh restore. The debounce + this guard
                    // together coalesce one user action into one restore.
                    frm._avtk_pr_lock_restoring = false;
                }

                if (changed) {
                    frm.dirty();
                    frm.refresh_field("items");
                    // Single coherent recalc derives base_rate,
                    // base_price_list_rate, net_rate, base_net_rate,
                    // amount, base_amount from the restored doc fields
                    // + current conversion_rate. Works for any currency
                    // pair, any margin/discount config, any PLE.
                    if (frm.cscript && frm.cscript.calculate_taxes_and_totals) {
                        frm.cscript.calculate_taxes_and_totals();
                    }
                }
            },
        });
    }, 150);
}

frappe.ui.form.on('Purchase Invoice', {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button("Payment Request Form", function() {
                frappe.model.open_mapped_doc({
                    method: "avientek.events.purchase_invoice.create_payment_request",
                    frm: frm
                });
            }, "Create");
        }
        // PR→PI conversion runs set_missing_values on load and may
        // already have scrambled the rates before the user touches
        // anything. Restore once on first refresh of a draft PI that
        // carries pr_detail rows.
        if (frm.doc.docstatus === 0) {
            _avtk_restore_pr_locked_pricing(frm);
        }
    },

    // All triggers that flow into ERPNext's exchange-rate / rate recalc.
    // The debounce in _avtk_restore_pr_locked_pricing coalesces back-to-
    // back fires from a single user action (e.g. posting_date change
    // can cascade into conversion_rate and plc_conversion_rate).
    posting_date:        _avtk_restore_pr_locked_pricing,
    bill_date:           _avtk_restore_pr_locked_pricing,
    conversion_rate:     _avtk_restore_pr_locked_pricing,
    currency:            _avtk_restore_pr_locked_pricing,
    plc_conversion_rate: _avtk_restore_pr_locked_pricing,
    price_list_currency: _avtk_restore_pr_locked_pricing,

    // ── Client Script: "PI" - filter supplier by company ──
    company: function(frm) {
        frm.set_query("supplier", function() {
            return {
                "filters": {
                    'company': ['in', [frm.doc.company, '']]
                }
            };
        });
    }
});