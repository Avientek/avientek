// Sridhar/Rahul 2026-06-10: when a PI is created from a PR and the user
// then changes posting_date / conversion_rate / currency / bill_date in
// the UI, ERPNext's posting_date trigger fires set_exchange_rate which
// re-derives each item's rate using the new PLE + cached discount_amount —
// producing nonsense numbers in the grid (sometimes negative; e.g. row 1
// $-164.00, row 2 $570.00 from a PR where both rows were $665.00).
//
// The server-side preserve_pr_rate hook restores correct rates on
// validate (save), but the UI between conversion and save shows the
// scrambled values, leading users to think the system is broken. This
// client-side restore mirrors the server hook: after each trigger that
// could trip the recalc, call get_pr_locked_pricing and re-apply the
// PR row's pricing fields immediately. Idempotent — restoring already-
// correct rates is a no-op.
function _avtk_restore_pr_locked_pricing(frm) {
    if (!frm || !frm.doc || frm.doc.is_return) return;
    if (!(frm.doc.items || []).length) return;

    const pr_details = (frm.doc.items || [])
        .map(it => it.pr_detail)
        .filter(Boolean);
    if (!pr_details.length) return;

    // Debounce: multiple triggers (posting_date + conversion_rate +
    // plc_conversion_rate) can fire in quick succession from a single
    // user action; only the last request matters.
    if (frm._avtk_pr_lock_pending) {
        clearTimeout(frm._avtk_pr_lock_pending);
    }
    frm._avtk_pr_lock_pending = setTimeout(function () {
        frm._avtk_pr_lock_pending = null;
        frappe.call({
            method: "avientek.events.purchase_invoice.get_pr_locked_pricing",
            args: { pr_details: pr_details },
            callback: function (r) {
                const pricing = (r && r.message) || {};
                if (!Object.keys(pricing).length) return;
                let changed = false;
                (frm.doc.items || []).forEach(function (it) {
                    const lock = pricing[it.pr_detail];
                    if (!lock) return;
                    Object.keys(lock).forEach(function (k) {
                        const v = lock[k];
                        if (v == null) return;
                        if (it[k] !== v) {
                            frappe.model.set_value(it.doctype, it.name, k, v);
                            changed = true;
                        }
                    });
                });
                if (changed) {
                    // Refresh the items grid so the new rate / net_rate
                    // become visible without requiring a form save.
                    frm.refresh_field("items");
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