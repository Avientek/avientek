frappe.ui.form.on('Payment Entry', {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button("Payment Request Form", function () {
                frappe.model.open_mapped_doc({
                    method: "avientek.events.payment_entry.create_payment_request",
                    frm: frm
                });
            }, "Create");
        }
    }
});
