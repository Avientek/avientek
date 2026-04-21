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

        // Zero out tax rates when item_tax_template is used
        var has_item_tax_template = frm.doc.items.some(function(item) { return item.item_tax_template; });
        if (has_item_tax_template && frm.doc.taxes) {
            frm.doc.taxes.forEach(function(tax) {
                tax.rate = 0;
            });
            frm.refresh_field('taxes');
        }
    }
});

// ── Client Script: "Purchase Receipt" (DISABLED) ──
// This script was disabled. It had additional onload logic for setting
// plc_conversion_rate from PO and zeroing margin_rate_or_amount.
// See server_client_scripts_backup.json for the full version.
