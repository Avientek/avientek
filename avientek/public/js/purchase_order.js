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
		if (!frm.doc.__islocal && frm.doc.docstatus != 2 && frm.doc.items) {
			let avientek_eta = []
			frm.doc.items.map((d) => {
				if(d.avientek_eta && d.avientek_eta != '') avientek_eta.push(d.avientek_eta)
			});
			if(avientek_eta.length > 0){
				frm.add_custom_button(__('Set SO ETA'),
					function() {
						frm.doc["items"].forEach(d => {
							if(d.avientek_eta && d.sales_order){
								var sales_order = String(d.sales_order)+ " | " + (String(d.sales_order_item))
								set_so_eta(frm, sales_order, d);
							}
						});
					}).addClass("btn-default");
			}
			else{
				frm.remove_custom_button('Set SO ETA')
			}
		}

	},
	avientek_eta: function(frm) {
		if (frm.doc.avientek_eta) {
			$.each(frm.doc.items, function(x, y) {
				frappe.model.set_value(y.doctype, y.name, {
					"avientek_eta": frm.doc.avientek_eta
				});
			});
		}
	},
	// validate: function(frm) {
	// 	frappe.run_serially([
	// 		() => set_display_exchange_rate(frm),
	// 		() => set_rate_from_avientek_rate(frm),
	// 		() => set_display_currency(frm),
	// 	]);
	// },
	avientek_display_currency: function(frm) {
		if (frm.doc.avientek_display_currency) {
			set_display_exchange_rate(frm)
		} else {
			frm.set_value("avientek_exchange_rate", 0)
		}
	},
	avientek_exchange_rate: function(frm) {
		set_display_currency(frm)
	},
	// custom_set_so_eta:function(frm) {
	// 	let avientek_eta = frm.doc.items.map(({ avientek_eta }) => avientek_eta);
	// 	if(avientek_eta){
	// 		frm.doc["items"].forEach(d => {
	// 			if(d.avientek_eta){
	// 				var sales_order = String(d.sales_order)+ " | " + (String(d.sales_order_item))
	// 				set_so_eta(frm, sales_order, d);
	// 			}
	// 		});
	// 	}
	// }
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
	qty: function(frm, cdt, cdn) {
		set_display_currency(frm)
	},
	// rate: function(frm, cdt, cdn) {
	// 	set_display_currency(frm)
	// },
	avientek_rate: function(frm, cdt, cdn) {
		set_rate_from_avientek_rate(frm, cdt, cdn)
	}
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

var set_display_currency = function(frm) {
	let frm_value_list = [{'avientek_field': 'avientek_total', 'core_field':frm.doc.total},
			{'avientek_field': 'avientek_grand_total', 'core_field':frm.doc.grand_total},
			{'avientek_field': 'avientek_rounding_adjustment', 'core_field':frm.doc.rounding_adjustment},
			{'avientek_field': 'avientek_rounded_total', 'core_field':frm.doc.rounded_total}]
	if(	frm.doc.avientek_exchange_rate) {
		frm_value_list.forEach(val=> {
			frm.set_value(val.avientek_field, (frm.doc.avientek_exchange_rate*val.core_field))
		})
		$.each(frm.doc.items, function(x, y) {
			frappe.model.set_value(y.doctype, y.name, 'avientek_rate', (frm.doc.avientek_exchange_rate*y.rate))
			frappe.model.set_value(y.doctype, y.name, 'avientek_amount', (frm.doc.avientek_exchange_rate*y.rate*y.qty))
		})
	} else {
		frm_value_list.forEach(val=> {
			frm.set_value(val.avientek_field, 0)
		})
		$.each(frm.doc.items, function(x, y) {
			frappe.model.set_value(y.doctype, y.name, 'avientek_rate', 0)
			frappe.model.set_value(y.doctype, y.name, 'avientek_amount', 0)
		})
	}
}

var set_display_exchange_rate = function(frm) {
	frm.refresh();
	if (frm.doc.currency && frm.doc.avientek_display_currency) {
		frappe.call({
			'method': 'erpnext.setup.utils.get_exchange_rate',
			'args':{
				'from_currency': frm.doc.currency,
				'to_currency': frm.doc.avientek_display_currency
		},
		freeze: true,
		callback: (r) => {
			if(!r.exc) {
				if (r.message) {
					frm.set_value("avientek_exchange_rate", r.message)
				} else {
					frm.set_value("avientek_exchange_rate", 0)
				}
			} else {
				frm.set_value("avientek_exchange_rate", 0)
			}
		}
		})
	}
}

var set_rate_from_avientek_rate = function(frm, cdt, cdn) {
	let child = locals[cdt][cdn];
	if(frm.doc.avientek_exchange_rate) {
		frappe.model.set_value(cdt, cdn, 'avientek_exchange_rate', frm.doc.avientek_exchange_rate)

		if (child.avientek_rate) {
			frappe.model.set_value(cdt, cdn, 'rate', (child.avientek_rate/frm.doc.avientek_exchange_rate))
		}
	} else {
		frappe.model.set_value(cdt, cdn, 'avientek_exchange_rate', 0)
	}
}
