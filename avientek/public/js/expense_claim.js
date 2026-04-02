frappe.ui.form.on('Expense Claim', {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button("Payment Request Form", function() {
                frappe.model.open_mapped_doc({
                    method: "avientek.events.expense_claim.create_payment_request",
                    frm: frm
                });
            }, "Create");
        }
    },

    // ── Client Script: "Company Filter based on employee" ──
    employee: function(frm) {
        if (frm.doc.employee) {
            frappe.call({
                method: 'frappe.client.get_value',
                args: {
                    doctype: 'Employee',
                    filters: { name: frm.doc.employee },
                    fieldname: ['company']
                },
                callback: function(r) {
                    if (r.message) {
                        frm.set_query('company', function() {
                            return {
                                filters: { 'name': r.message.company }
                            };
                        });
                    }
                }
            });
        }
    }
});