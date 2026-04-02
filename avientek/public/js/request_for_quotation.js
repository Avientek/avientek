// ── Client Script: "RFQ" ──
frappe.ui.form.on('Request for Quotation', {
    setup: function(frm) {
        frm.set_query("supplier", "suppliers", function() {
            return {
                "filters": {
                    'company': ['in', [frm.doc.company, '']]
                }
            };
        });
    }
});
