frappe.ui.form.on('Purchase Order',{
    refresh:function(frm){
        if(frm.doc.__islocal){
            console.log("????????????????????????????/")
            frm.add_custom_button(__('Child company sales order'),
                function() {
                    erpnext.utils.map_current_doc({
                        method: "avientek.events.purchase_order.make_purchase_order",
                        source_doctype: "Sales Order",
                        target: me.frm,
                        setters: {
                            schedule_date: undefined,
                            status: undefined
                        },
                        get_query_filters: {
                            docstatus: 1,
                        },
                        allow_child_item_selection: true,
                        child_fieldname: "items",
                        child_columns: ["item_code", "qty"]
                    })
                }, __("Get Items From"));
        }
    },
})