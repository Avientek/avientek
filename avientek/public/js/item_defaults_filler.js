/**
 * Fills mandatory item_name / uom / stock_uom / description / conversion_factor
 * when only item_code is populated on a transaction row. Triggered primarily
 * by CSV/Excel bulk upload into the items grid — that path bypasses ERPNext's
 * item_code cascade, so rows land with just item_code and Frappe's client-side
 * mandatory validation blocks save.
 */
(function () {
    const CHILD_DOCTYPES = [
        "Quotation Item",
        "Sales Order Item",
        "Delivery Note Item",
        "Sales Invoice Item",
        "Purchase Order Item",
        "Purchase Invoice Item",
        "Purchase Receipt Item",
    ];

    function fill_from_item(cdt, cdn) {
        const row = locals[cdt] && locals[cdt][cdn];
        if (!row || !row.item_code) return;
        if (row.item_name && row.uom) return;

        frappe.db.get_value("Item", row.item_code, ["item_name", "stock_uom", "description"])
            .then(function (r) {
                const d = (r && r.message) || {};
                const latest = locals[cdt][cdn];
                if (!latest) return;
                if (!latest.item_name && d.item_name) {
                    frappe.model.set_value(cdt, cdn, "item_name", d.item_name);
                }
                if (!latest.uom && d.stock_uom) {
                    frappe.model.set_value(cdt, cdn, "uom", d.stock_uom);
                }
                if (!latest.stock_uom && d.stock_uom) {
                    frappe.model.set_value(cdt, cdn, "stock_uom", d.stock_uom);
                }
                if (!latest.description && (d.description || d.item_name)) {
                    frappe.model.set_value(cdt, cdn, "description", d.description || d.item_name);
                }
                if (!latest.conversion_factor) {
                    frappe.model.set_value(cdt, cdn, "conversion_factor", 1);
                }
            });
    }

    CHILD_DOCTYPES.forEach(function (cdt) {
        frappe.ui.form.on(cdt, {
            item_code: function (frm, triggered_cdt, triggered_cdn) {
                fill_from_item(triggered_cdt, triggered_cdn);
            },
        });
    });
})();
