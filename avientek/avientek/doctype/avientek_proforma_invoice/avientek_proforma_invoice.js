frappe.ui.form.on('Avientek Proforma Invoice',{
	refresh:function(frm){
    }
})
frappe.ui.form.on('Proforma Invoice Item',{
    qty: function(frm, cdt, cdn){
        set_amount(frm, cdt, cdn)
    },
    item_code:function(frm, cdt, cdn){
        frappe.model.set_value(cdt, cdn, 'rate', 0)
        set_amount(frm, cdt, cdn)
    },
    rate:function(frm, cdt, cdn){
        set_amount(frm, cdt, cdn)
    }
})

var set_amount = function(frm, cdt, cdn){
    let child = locals[cdt][cdn]
    if (frm.doc.items){
        let amount = (child.qty)*(child.rate)
        frappe.model.set_value(cdt, cdn, "amount",amount)
    }
}
