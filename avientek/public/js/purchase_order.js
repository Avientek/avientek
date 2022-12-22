frappe.ui.form.on('Purchase Order',{
	refresh:function(frm){
		// if(frm.doc.__islocal){
		// 	frm.add_custom_button(__('Child company sales order'),
		// 		function() {
		// 			erpnext.utils.map_current_doc({
		// 				method: "avientek.events.purchase_order.make_purchase_order",
		// 				source_doctype: "Sales Order",
		// 				target: me.frm,
		// 				setters: {
		// 					schedule_date: undefined,
		// 					status: undefined
		// 				},
		// 				get_query_filters: {
		// 					docstatus: 1,
		// 				},
		// 				allow_child_item_selection: true,
		// 				child_fieldname: "items",
		// 				child_columns: ["item_code", "qty"]
		// 			})
		// 		}, __("Get Items From"));
		// }
	},
})

frappe.ui.form.on("Purchase Order Item", {
	swap_so: function(frm, cdt, cdn) {
		add_so_dialog(frm, cdt, cdn);
	},
	set_so_eta: function(frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		var sales_order = String(row.sales_order)+ " | " + (String(row.sales_order_item))
		set_so_eta(frm, sales_order, row);
	},
})

var add_so_dialog = function (frm, cdt, cdn) {
	var row = locals[cdt][cdn];
	frappe.call({
		'method': 'avientek.events.purchase_order.get_sales_orders',
		'args':{
			'item': row.item_code,
			'qty': row.qty,
			'sales_order': row.sales_order
		},
	freeze: true,
	callback: (r) => {
		if (r && r.message) {
			let d = new frappe.ui.Dialog({
				title: 'Swap Sales Order',
				fields: [
					{
						label: 'Sales Order',
						fieldname: 'sales_order',
						fieldtype: 'Select',
						options: r.message
					}
				],
				primary_action_label: 'Swap',
				primary_action(values) {
					if (values && values.sales_order) {
						set_so_eta(frm, values.sales_order, row)
					}
					d.hide();
				}
			});
			d.show();
		}
	}
	})
}

var set_so_eta = function(frm, sales_order,row) {
	frappe.call({
		'method': 'avientek.events.purchase_order.set_sales_order',
		'args':{
			'sales_order': sales_order,
			'item_name': row.name,
			'eta': row.avientek_eta
		},
		freeze: true,
		callback: (r) => {
			if(!r.exc) {
				frm.reload_doc();
				frappe.show_alert({
					message:__('Sales Order Updated'),
					indicator:'green'
				}, 5);
			}
		}
	})
}