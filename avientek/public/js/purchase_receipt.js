frappe.ui.form.on('Purchase Receipt', {
    onload: function(frm) {
        if (frm.doc.docstatus == 0) {
            const purchase_order = frm.doc.items[0].purchase_order;
            if(purchase_order) {
                frappe.db.get_value("Purchase Order", purchase_order, "plc_conversion_rate").then(r => {
                    if(r && r.message) {
                        setTimeout(() => {
                            frm.set_value("plc_conversion_rate", r.message.plc_conversion_rate).then(() => {
                                frm.refresh_field("plc_conversion_rate");
                            }).catch(err => {
                                console.log("Error setting plc_conversion_rate:", err);
                            });
                        }, 500); // 2-second delay
                    }
                }).catch(err => {
                    console.log("Error retrieving plc_conversion_rate:", err);
                });
            }
        }
        if (frm.doc.__islocal){
            setTimeout(() => {
                frm.doc.items.forEach(item =>{
                frappe.model.set_value(item.doctype, item.name, 'margin_rate_or_amount',0)
                })
            },1000)
		}
    }
});
