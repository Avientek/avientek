frappe.ui.form.on('Sales Order',{
	// ── Client Script: "Fetch Customer Name" - filter customer by company ──
	setup: function(frm) {
		if (frm.doc.company) {
			frappe.call({
				"method": "avientek.api.filtered_parties.get_filtered_customers",
				"args": { 'company': frm.doc.company },
				callback: function(r) {
					if (r.message) {
						frm.set_query("customer", function() {
							return { "filters": { 'name': ['in', r.message] } };
						});
					}
				}
			});
		}
	},

	company: function(frm) {
		frappe.call({
			"method": "avientek.api.filtered_parties.get_filtered_customers",
			"args": { 'company': frm.doc.company },
			callback: function(r) {
				if (r.message) {
					frm.set_query("customer", function() {
						return { "filters": { 'name': ['in', r.message] } };
					});
				}
			}
		});
	},

	// ── Client Script: "Fetch Customer Name" - sync delivery_date and customer_name ──
	onload: function(frm) {
		if (frm.doc.docstatus === 1) return;
		if (frm.doc.customer) {
			frappe.db.get_value('Customer', frm.doc.customer, 'customer_name')
				.then(r => {
					if (r && r.message) {
						frm.set_value('customer_name', r.message.customer_name);
					}
				});
		}
	},

	delivery_date: function(frm) {
		if (frm.doc.delivery_date) {
			frm.doc.items.forEach(function(item) {
				frappe.model.set_value(item.doctype, item.name, 'delivery_date', frm.doc.delivery_date);
			});
		}
	},

	// ── Client Script: "Fetch Customer Name" - discount logic ──
	discount_amount: function(frm) {
		if (frm.doc.apply_discount_on !== "Net Total") {
			frappe.throw(__("Discount is only allowed when 'Apply Discount On' is set to <b>Net Total</b>."));
			return;
		}

		if (frm._discount_timer) clearTimeout(frm._discount_timer);

		frm._discount_timer = setTimeout(function() {
			var total = parseFloat(frm.doc.total) || 0;
			var discount = parseFloat(frm.doc.discount_amount) || 0;

			if (discount > 0 && total > 0) {
				var perc = (discount / total) * 100;
				frm.set_value('additional_discount_percentage', parseFloat(perc.toFixed(6)));
			}
		}, 1000);
	},

	additional_discount_percentage: function(frm) {
		if (frm.doc.apply_discount_on !== "Net Total") {
			frappe.throw(__("Discount is only allowed when 'Apply Discount On' is set to <b>Net Total</b>."));
			return;
		}

		var total = parseFloat(frm.doc.total) || 0;
		var perc = parseFloat(frm.doc.additional_discount_percentage) || 0;

		if (perc > 0 && total > 0) {
			var amt = (perc / 100) * total;
			frm.set_value('discount_amount', parseFloat(amt.toFixed(2)));
		}
	},

	// ── Client Script: "Fetch Customer Name" - auto share with sales team ──
	after_save: async function(frm) {
		await _shareSalesOrderWithUsers(frm);
	},

	refresh:function(frm){
		// ── Client Script: "SO Hide item" - control buttons ──
		_control_so_buttons(frm);
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

// ── Client Script: "SO Hide item" - control Update Items / Status buttons ──
var _so_button_observer = null;

function _control_so_buttons(frm) {
	var isAllowedState = [
		"Approved for Update",
		"Sent for Revision"
	].indexOf(frm.doc.workflow_state) !== -1;

	var styleId = 'so-button-control-style';
	if (!document.getElementById(styleId)) {
		var styleEl = document.createElement('style');
		styleEl.id = styleId;
		styleEl.textContent = '[data-so-hidden="true"] { display: none !important; }';
		document.head.appendChild(styleEl);
	}

	function applyToButtons() {
		frm.page.wrapper.find('button').each(function() {
			var $btn = $(this);
			var text = $btn.text().trim();

			if (text === 'Update Items' || text === 'Status') {
				$btn.attr('data-so-hidden', isAllowedState ? null : 'true');
			}
		});
	}

	applyToButtons();

	if (_so_button_observer) {
		_so_button_observer.disconnect();
		_so_button_observer = null;
	}

	var toolbar = frm.page.wrapper.find('.page-actions')[0];
	if (!toolbar) return;

	_so_button_observer = new MutationObserver(function(mutations) {
		var hasNewNodes = mutations.some(function(m) { return m.type === 'childList' && m.addedNodes.length; });
		if (hasNewNodes) applyToButtons();
	});

	_so_button_observer.observe(toolbar, { childList: true, subtree: true });

	setTimeout(function() {
		if (_so_button_observer) {
			_so_button_observer.disconnect();
			_so_button_observer = null;
		}
	}, 5000);
}

// ── Client Script: "Fetch Customer Name" - auto share with sales team ──
async function _shareSalesOrderWithUsers(frm) {
	if (!frm.doc.sales_team || frm.doc.sales_team.length === 0) return;

	var salesPersons = frm.doc.sales_team
		.map(function(row) { return row.sales_person; })
		.filter(Boolean);

	if (salesPersons.length === 0) return;

	var allSalesPersons = new Set(salesPersons);

	await Promise.all(salesPersons.map(function(sp) {
		return frappe.db.get_value('Sales Person', sp, 'parent_sales_person')
			.then(function(res) {
				if (res && res.message && res.message.parent_sales_person) {
					allSalesPersons.add(res.message.parent_sales_person);
				}
			});
	}));

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "User Permission",
			filters: {
				allow: "Sales Person",
				for_value: ["in", Array.from(allSalesPersons)]
			},
			fields: ["user"],
			limit_page_length: 100
		},
		callback: function(res) {
			if (!res.message || res.message.length === 0) return;

			var users = [...new Set(res.message.map(function(r) { return r.user; }))];

			users.forEach(function(user) {
				frappe.call({
					method: "frappe.client.get_list",
					args: {
						doctype: "DocShare",
						filters: {
							user: user,
							share_doctype: frm.doc.doctype,
							share_name: frm.doc.name
						},
						limit_page_length: 1
					},
					callback: function(res) {
						if (res.message && res.message.length > 0) return;
						frappe.call({
							method: "frappe.client.insert",
							args: {
								doc: {
									doctype: "DocShare",
									user: user,
									share_doctype: frm.doc.doctype,
									share_name: frm.doc.name,
									read: 1,
									write: 1,
									share: 1,
									submit: 1
								}
							}
						});
					}
				});
			});
		}
	});
}

// ── Client Script: "Validate Exchange Rate in Intercompany" (DISABLED) ──
// frappe.ui.form.on('Sales Order', {
//     onload: function(frm) {
//         if ((frm.doc.currency == frm.doc.price_list_currency) &&
//             (frm.doc.conversion_rate != frm.doc.plc_conversion_rate)) {
//             frappe.throw("Exchange rate and price list exchange rate should be the same!");
//         }
//     }
// });
