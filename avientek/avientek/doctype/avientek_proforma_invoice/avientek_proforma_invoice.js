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

frappe.ui.form.on('Sales Taxes and Charges',{
	rate:function(frm, cdt, cdn){
        let row = locals[cdt][cdn]
        if (frm.doc.total){
            let tax_amount = (row.rate/100)*frm.doc.total
            let total_amount = tax_amount + frm.doc.total
            frappe.model.set_value(cdt,cdn,"tax_amount", tax_amount)
            frappe.model.set_value(cdt,cdn,"total", total_amount)
        }
    }
})

var set_amount = function(frm, cdt, cdn){
    let child = locals[cdt][cdn]
    if (frm.doc.items){
        let amount = (child.qty)*(child.rate)
        frappe.model.set_value(cdt, cdn, "amount",amount)
    }
}
