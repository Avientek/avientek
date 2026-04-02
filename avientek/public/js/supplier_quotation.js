// ── Client Script: "Supplier Quotation" ──
frappe.ui.form.on("Supplier Quotation", {
    refresh: function(frm) {
        frm.set_query("supplier", function() {
            return {
                "filters": {
                    'company': ['in', [frm.doc.company, '']]
                }
            };
        });
    }
});
