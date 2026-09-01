frappe.ui.form.on('Purchase Order',{
	// ── Client Script: "Terms Company Filter" ──
	onload: function(frm) {
		_set_tc_name_query(frm);
	},

	// ── Client Script: "PO update item button hide" ──
	onload_post_render: function(frm) {
		_control_po_buttons(frm);
	},

	refresh:function(frm){
		_set_tc_name_query(frm);
		// ── Client Script: "PO update item button hide" ──
		setTimeout(function() { _control_po_buttons(frm); }, 200);
		if (!frm.doc.__islocal && frm.doc.docstatus === 1) {
            frm.add_custom_button("Payment Request Form", function () {
            frappe.model.open_mapped_doc({
				method: "avientek.events.purchase_order.create_payment_request",
				frm: frm
			})
            }, "Create");
        }
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
						let so = frm.doc.items.map(({ sales_order }) => sales_order);
						var arrayso = Array.from(new Set(so))
						var unique_so = arrayso.filter(e => {return !['',undefined].includes(e)});
						console.log(unique_so)
						frm.doc["items"].forEach(d => {
							if(d.avientek_eta && d.sales_order){
								var sales_order = String(d.sales_order)+ " | " + (String(d.sales_order_item))
								set_so_eta(frm, sales_order, d);
							}
						});
						unique_so.forEach(val=> {
							console.log(val) 
							send_notification(frm,'Sales Order',val,0)});
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
	conversion_rate:function(frm){
		setTimeout(() => {
			frm.set_value("plc_conversion_rate" ,frm.doc.conversion_rate)
		}, 2000);
	},
	avientek_exchange_rate: function(frm) {
		set_display_currency(frm)
	},

	// ── Client Script: "Terms Company Filter" ──
	company: function(frm) {
		_set_tc_name_query(frm);
		// ── Client Script: "PO" (enabled) - filter supplier by company ──
		if (frm.doc.company) {
			frappe.call({
				"method": "avientek.api.filtered_parties.get_filtered_supplier",
				"args": { 'company': frm.doc.company },
				callback: function(r) {
					if (r.message) {
						frm.set_query("supplier", function() {
							return { "filters": { 'name': ['in', r.message] } };
						});
					}
				}
			});
		}
	},

	// Sridhar 2026-08-31: picking a supplier swaps the PO currency and
	// conversion rate instantly, so repaint Special Price to match instead
	// of leaving an SO-currency figure under the new symbol until save.
	// currency fires first (rate still stale), conversion_rate fires once
	// the async rate lookup settles — hooking both means the column is
	// right whichever of the two actually moves.
	currency: function(frm) {
		refresh_special_price(frm);
	},

	conversion_rate: function(frm) {
		refresh_special_price(frm);
	},

	setup: function(frm) {
		if (frm.doc.company) {
			frappe.call({
				"method": "avientek.api.filtered_parties.get_filtered_supplier",
				"args": { 'company': frm.doc.company },
				callback: function(r) {
					if (r.message) {
						frm.set_query("supplier", function() {
							return { "filters": { 'name': ['in', r.message] } };
						});
					}
				}
			});
		}
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
		console.log("sales_order",sales_order)
		set_so_eta(frm, sales_order, row);
		send_notification(frm,'Purchase Order',frm.doc.name,row.item_code)
		send_notification(frm,'Sales Order',row.sales_order,row.item_code)
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
	console.log("set eta",row.avientek_eta)
	// frappe.model.set_value(row.doctype,row.name,'avientek_eta',row.avientek_eta)
	frappe.call({
		'method': 'avientek.events.purchase_order.line_update_eta',
		'args':{
			'item': row,
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

var send_notification = function(frm, ref_doctype,ref_name,item) {
	console.log("senddddddddddd",ref_doctype,ref_name,item)
	frappe.call({
		'method': 'avientek.events.purchase_order.create_notification',
		'args':{
			'ref_doctype': ref_doctype,
			'ref_name': ref_name,
			'item': item
		},
		freeze: true,
		callback: (r) => {
			if(!r.exc) {
				frappe.show_alert({
					message:__('Notification Sent'),
					indicator:'green'
				}, 5);
			}
		}
	})
}

// Sridhar 2026-08-31: repaint the read-only Special Price column in the PO's
// current currency. Display-only — sync_special_price_from_sales_order()
// recomputes the same figures server-side on every save, so a call that is
// skipped or fails just delays the repaint, it can never persist a wrong
// number. No freeze: this fires while the user is still filling the header.
var refresh_special_price = function(frm) {
	if (frm.doc.docstatus !== 0) return;
	if (!frm.doc.currency || !frm.doc.conversion_rate || !frm.doc.items) return;

	var so_items = frm.doc.items
		.filter(function(d) { return d.sales_order_item; })
		.map(function(d) { return d.sales_order_item; });
	if (!so_items.length) return;

	frappe.call({
		method: 'avientek.events.purchase_order.get_special_prices_for_currency',
		args: {
			sales_order_items: so_items,
			currency: frm.doc.currency,
			conversion_rate: frm.doc.conversion_rate
		},
		callback: function(r) {
			if (r.exc || !r.message) return;
			frm.doc.items.forEach(function(d) {
				if (!d.sales_order_item) return;
				var val = r.message[d.sales_order_item];
				if (val === undefined) return;
				// Skip no-op writes so a same-currency PO is never marked dirty.
				if (flt(val) === flt(d.custom_special_price)) return;
				frappe.model.set_value(d.doctype, d.name, 'custom_special_price', val);
			});
		}
	});
};

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

// ── Client Script: "Terms Company Filter" ──
function _set_tc_name_query(frm) {
	if (frm.doc.company) {
		frm.set_query('tc_name', function() {
			return {
				filters: { custom_company: frm.doc.company }
			};
		});
	} else {
		frm.set_query('tc_name', function() {
			return {};
		});
	}
}

// ── Client Script: "PO update item button hide" ──
function _control_po_buttons(frm) {
	var shouldShow = (
		frm.doc.workflow_state === "Approved for Update" ||
		frm.doc.workflow_state === "Sent for Revision" ||
		frm.doc.workflow_state === "Draft"
	);

	var update_btn = $('button:contains("Update Items")');
	var get_items_selectors = [
		'button:contains("Get Items From")',
		'.btn-group:has(button:contains("Get Items From"))',
		'button.dropdown-toggle:contains("Get Items From")'
	];

	if (shouldShow) {
		update_btn.show();
		get_items_selectors.forEach(function(selector) { $(selector).show(); });
	} else {
		update_btn.hide();
		get_items_selectors.forEach(function(selector) { $(selector).hide(); });
	}
}

// ── Client Script: "Update PO update button" (DISABLED) ──
// This was a more elaborate version with MutationObserver.
// The simpler _control_po_buttons above (from "PO update item button hide") is active.
// See server_client_scripts_backup.json for the full disabled version.
