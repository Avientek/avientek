frappe.ui.form.on('Purchase Receipt', {
    onload: function(frm) {
    	if (frm.doc.conversion_rate != frm.doc.plc_conversion_rate) {
	    	if (frm.doc.__islocal){
		      frm.doc.items.forEach(item =>{
		      	var discount_amount = item.discount_amount
		      	frappe.model.set_value(item.doctype, item.name, 'discount_amount',0)
		        frappe.model.set_value(item.doctype, item.name, 'margin_rate_or_amount',Math.abs(discount_amount))
		        
		      })
		      frappe.db.get_value("Purchase Order", purchase_order, "plc_conversion_rate").then(r => {
                if(r && r.message) {
                    setTimeout(() => {
                        frm.set_value("plc_conversion_rate", r.message.plc_conversion_rate).then(() => {
                            frm.refresh_field("plc_conversion_rate");
                        }).catch(err => {
                            console.log("Error setting plc_conversion_rate:", err);
                        });
                    }, 2000);
                }
                }).catch(err => {
                    console.log("Error retrieving plc_conversion_rate:", err);
                });
		    }
		}
    }
});
