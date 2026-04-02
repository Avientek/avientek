// ── Client Script: "Payment request confirmation email" ──
frappe.ui.form.on('Payment Request', {
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
                        frm.set_value('email_to', r.message[documents[frm.doc.party_type]]);
                    });
            }
        }
    }
});
