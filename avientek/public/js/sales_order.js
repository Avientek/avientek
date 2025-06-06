frappe.ui.form.on('Sales Order',{
	refresh:function(frm){
		if (frm.doc.docstatus===1){
			frm.add_custom_button(__('Proforma Invoice'),() => {
			frappe.model.open_mapped_doc({
				method: "avientek.events.sales_order.create_proforma_invoice",
				frm: frm
			})
        },__('Create'));
		}
		// var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
		// const purchase_order = frm.doc.items[0].purchase_order;
		
		// if (frm.doc.__islocal){
		// 	frm.doc.items.forEach(item =>{
		// 		frappe.model.set_value(item.doctype, item.name, 'margin_rate_or_amount',0)
		// 	})
		// }

		// if (frm.doc.docstatus == 0) {
		// 	frappe.call({
		// 		method: "erpnext.setup.utils.get_exchange_rate",
		// 		args: {
		// 			from_currency:frm.doc.currency,
		// 			to_currency: company_currency
		// 		},
		// 		callback: function(r) {
		// 			frappe.db.get_value("Purchase Order",purchase_order,"company").then(res => {
		// 				var company_currency1 = frappe.get_doc(":Company", res.message.company).default_currency;
		// 				if (r.message && company_currency != company_currency1) {
		// 					frm.set_value("conversion_rate",r.message)
		// 				}
		// 			})
					
		// 		}
		// 	});
		// }
	},
	

	
	// onload: function(frm) {
	// 	frappe.db.get_value('Customer', frm.doc.customer, 'avientek_display_currency')
	// 	.then(r => {
	// 		frm.set_value('avientek_display_currency', r.message.avientek_display_currency)
	// 	})
	// },
	// onload_post_render: function(frm) {
	// 	if (frm.doc.docstatus==0) {
	// 		frappe.run_serially([
	// 			() => set_new_rate(frm),
	// 			() => set_display_exchange_rate(frm),
	// 			() => set_display_currency(frm),
	// 		]);
	// 	}
	// },
	// before_save: function(frm) {
	// 	frappe.run_serially([
	// 		() => set_new_rate(frm),
	// 		() => set_display_exchange_rate(frm),
	// 		() => set_display_currency(frm),
	// 	]);
	// },
	// avientek_display_currency: function(frm) {
	// 	if (frm.doc.avientek_display_currency) {
	// 		set_display_exchange_rate(frm)
	// 	} else {
	// 		frm.set_value("avientek_exchange_rate", 0)
	// 	}
	// },
	// avientek_exchange_rate: function(frm) {
	// 	set_display_currency(frm)
	// }
})

// frappe.ui.form.on("Sales Order Item", {
// 	avientek_rate: function(frm, cdt, cdn) {
// 		set_rate_from_avientek_rate(frm, cdt, cdn)
// 	}
// })


// var set_display_currency = function(frm) {
// 	let frm_value_list = [{'avientek_field': 'avientek_total', 'core_field':frm.doc.total},
// 			{'avientek_field': 'avientek_grand_total', 'core_field':frm.doc.grand_total},
// 			{'avientek_field': 'avientek_rounding_adjustment', 'core_field':frm.doc.rounding_adjustment},
// 			{'avientek_field': 'avientek_rounded_total', 'core_field':frm.doc.rounded_total}]
// 	if(	frm.doc.avientek_exchange_rate) {
// 		frm_value_list.forEach(val=> {
// 			frm.set_value(val.avientek_field, (frm.doc.avientek_exchange_rate*val.core_field))
// 		})
// 		$.each(frm.doc.items, function(x, y) {
// 			frappe.model.set_value(y.doctype, y.name, 'avientek_exchange_rate', frm.doc.avientek_exchange_rate)
// 			frappe.model.set_value(y.doctype, y.name, 'avientek_rate', (frm.doc.avientek_exchange_rate*y.rate))
// 			frappe.model.set_value(y.doctype, y.name, 'avientek_amount', (frm.doc.avientek_exchange_rate*y.rate*y.qty))
// 		})
// 	} else {
// 		frm_value_list.forEach(val=> {
// 			frm.set_value(val.avientek_field, 0)
// 		})
// 		$.each(frm.doc.items, function(x, y) {
// 			frappe.model.set_value(y.doctype, y.name, 'avientek_exchange_rate', 0)
// 			frappe.model.set_value(y.doctype, y.name, 'avientek_rate', 0)
// 			frappe.model.set_value(y.doctype, y.name, 'avientek_amount', 0)
// 		})
// 	}
// }

// var set_display_exchange_rate = function(frm) {
// 	if (frm.doc.currency && frm.doc.avientek_display_currency) {
// 		frappe.call({
// 			'method': 'erpnext.setup.utils.get_exchange_rate',
// 			'args':{
// 				'from_currency': frm.doc.currency,
// 				'to_currency': frm.doc.avientek_display_currency
// 		},
// 		freeze: true,
// 		callback: (r) => {
// 			if(!r.exc) {
// 				if (r.message) {
// 					frm.set_value("avientek_exchange_rate", r.message)
// 				} else {
// 					frm.set_value("avientek_exchange_rate", 0)
// 				}
// 			} else {
// 				frm.set_value("avientek_exchange_rate", 0)
// 			}
// 		}
// 		})
// 	}
// }

// var set_rate_from_avientek_rate = function(frm, cdt, cdn) {
// 	let child = locals[cdt][cdn];
// 	if(frm.doc.avientek_exchange_rate) {
// 		frappe.model.set_value(cdt, cdn, 'avientek_exchange_rate', frm.doc.avientek_exchange_rate)

// 		if (child.avientek_rate) {
// 			frappe.model.set_value(cdt, cdn, 'rate', (child.avientek_rate/frm.doc.avientek_exchange_rate))
// 		}
// 	} else {
// 		frappe.model.set_value(cdt, cdn, 'avientek_exchange_rate', 0)
// 	}
// }

// var set_new_rate = function(frm) {
// 	if (frm.doc.items) {
// 		$.each(frm.doc.items, function(x, y) {
// 			if (y.purchase_order && y.purchase_order_item) {
// 			frappe.call({
// 				'method': 'avientek.events.utils.get_previous_doc_rate_and_currency',
// 				'args':{
// 					'doctype': y.purchase_order,
// 					'child': y.purchase_order_item
// 				},
// 				freeze: true,
// 				callback: (r) => {
// 					if (r.message[0].currency != frm.doc.currency) {
// 						if (frm.doc.currency && frm.doc.avientek_display_currency) {
// 							frappe.call({
// 								'method': 'erpnext.setup.utils.get_exchange_rate',
// 								'args':{
// 									'from_currency': r.message[0].currency,
// 									'to_currency': frm.doc.currency
// 							},
// 							freeze: true,
// 							callback: (val) => {
// 								if(!val.exc) {
// 									if (val.message) {
// 										frappe.model.set_value(y.doctype, y.name, 'rate', (r.message[0].rate*val.message))
// 									}
// 								}
// 							}
// 							})
// 						}
// 					}
// 					frm.refresh_field("items")
// 				}
// 			});
// 			}
// 		})
// 	}
// }

// var set_new_rate = function(frm) {
// 	if (frm.doc.items) {
// 		let item_list = [];
// 		$.each(frm.doc.items, function(x, y) {
// 			item_list.push({'doctype': y.purchase_order,
// 				'child': y.purchase_order_item,
// 				'child_doctype': y.doctype,
// 				'child_name': y.name})
// 		})
// 		frappe.call({
// 			'method': 'avientek.events.utils.get_previous_doc_rate_and_currency',
// 			'args':{
// 				'item_list': item_list,
// 			},
// 			freeze: true,
// 			callback: (r) => {
// 				$.each(r.message, function(x, y) {
// 				if (y.currency != frm.doc.currency) {
// 					if (frm.doc.currency && frm.doc.avientek_display_currency) {
// 						frappe.call({
// 							'method': 'erpnext.setup.utils.get_exchange_rate',
// 							'args':{
// 								'from_currency': y.currency,
// 								'to_currency': frm.doc.currency
// 						},
// 						freeze: true,
// 						callback: (val) => {
// 							if(!val.exc) {
// 								if (val.message) {
// 									// frappe.model.set_value(y.child_doctype, y.child_name, 'rate', (rounded_rate*rounded_xchange_rate))
// 									frappe.model.set_value(y.child_doctype, y.child_name, 'rate', (Math.round(((y.rate*val.message)+Number.EPSILON)*1000)/1000))
// 								}
// 							}
// 						}
// 						})
// 					}
// 				}
// 				})
// 				frm.refresh_field("items")
// 			}
// 		});
// 		}
// }
