frappe.ui.form.on('Avientek Proforma Invoice',{
	refresh:function(frm){

        // console.log('1111')
    }
})

frappe.ui.form.on('Proforma Invoice Item',{
	refresh:function(frm){
        
    },
    qty: function(frm, cdt, cdn){
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
