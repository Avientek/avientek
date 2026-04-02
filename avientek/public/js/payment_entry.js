// ── Client Script: "Payment Entry confirmation email" ──
frappe.ui.form.on('Payment Entry', {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button("Payment Request Form", function() {
                frappe.model.open_mapped_doc({
                    method: "avientek.events.payment_entry.create_payment_request",
                    frm: frm
                });
            }, "Create");
        }
    },

    setup: function(frm) {
        frm.set_query("party", function() {
            return {
                "filters": {
                    'company': frm.doc.company
                }
            };
        });
    },

    party_type: function(frm) {
        frm.set_query("party", function() {
            return {
                "filters": {
                    'company': frm.doc.company
                }
            };
        });
    },

    party: function(frm) {
        if (frm.doc.party_type && frm.doc.party) {
            let documents = {
                "Customer": "email_id",
                "Supplier": "email_id",
                "Employee": "prefered_email"
            };
            if (frm.doc.party_type != 'Shareholder') {
                frappe.db.get_value(frm.doc.party_type, frm.doc.party, documents[frm.doc.party_type])
                    .then(r => {
                        frm.set_value('contact_email', r.message[documents[frm.doc.party_type]]);
                    });
            }
        }
    }
});
