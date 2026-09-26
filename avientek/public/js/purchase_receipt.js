frappe.ui.form.on('Purchase Receipt', {
    // ── Client Script: "Validate exchange rate" - filter supplier by company ──
    company: function(frm) {
        frappe.call({
            "method": "avientek.api.filtered_parties.get_filtered_supplier",
            "args": { 'company': frm.doc.company },
            callback: function(r) {
                if (r.message) {
                    frm.set_query("supplier", function() {
                        return { "filters": { 'name': ['in', r.message] } };
                    });
                }
            }
        });
    },

    setup: function(frm) {
        if (frm.doc.company) {
            frappe.call({
                "method": "avientek.api.filtered_parties.get_filtered_supplier",
                "args": { 'company': frm.doc.company },
                callback: function(r) {
                    if (r.message) {
                        frm.set_query("supplier", function() {
                            return { "filters": { 'name': ['in', r.message] } };
                        });
                    }
                }
            });
        }
    },

    // ── Client Script: "Validate exchange rate" - HSN code validation ──
    validate: function(frm) {
        var targetCompany = 'Avientek Electronics Trading PVT. LTD';

        if (frm.doc.company === targetCompany) {
            frm.doc.items.forEach(function(item) {
                if (!item.gst_hsn_code) {
                    frappe.msgprint(__('HSN Code (gst_hsn_code) is mandatory for Avientek Electronics Trading PVT. LTD.'));
                    frappe.validated = false;
                }
            });
        }

        // Zero a tax row's own rate ONLY when its account is covered by an
        // item's Item Tax Template — ERPNext then takes the rate for that
        // account from each item's map, and items without it get 0 (the India
        // GST intent this was written for). #0550 (Avientek Singapore): the old
        // version zeroed EVERY row whenever any item had a template, so a row
        // whose account no template covers (2-05-01-28 GST 9% vs the template's
        // old "GST - AETPLS" 7% account) ended up at 0% on every item.
        var covered = {};
        (frm.doc.items || []).forEach(function(item) {
            if (!item.item_tax_rate) return;
            try {
                Object.keys(JSON.parse(item.item_tax_rate) || {}).forEach(function(acc) {
                    covered[acc] = true;
                });
            } catch (e) { /* malformed map — leave rates untouched */ }
        });
        var changed = false;
        (frm.doc.taxes || []).forEach(function(tax) {
            if (covered[tax.account_head] && flt(tax.rate) !== 0) {
                tax.rate = 0;
                changed = true;
            }
        });
        if (changed) frm.refresh_field('taxes');
    }
});

// ── Client Script: "Purchase Receipt" (DISABLED) ──
// This script was disabled. It had additional onload logic for setting
// plc_conversion_rate from PO and zeroing margin_rate_or_amount.
// See server_client_scripts_backup.json for the full version.
