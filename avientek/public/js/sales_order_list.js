frappe.listview_settings["Sales Order"] = {
	add_fields: [
		"base_grand_total",
		"customer_name",
		"currency",
		"delivery_date",
		"per_delivered",
		"per_billed",
		"status",
		"order_type",
		"name",
		"skip_delivery_note",
	],
	get_indicator: function (doc) {
		if (doc.status === "Closed") {
			// Closed
			return [__("Closed"), "green", "status,=,Closed"];
		} else if (doc.status === "On Hold") {
			// on hold
			return [__("On Hold"), "orange", "status,=,On Hold"];
		} else if (doc.status === "Completed") {
			return [__("Completed"), "green", "status,=,Completed"];
		} else if (!doc.skip_delivery_note && flt(doc.per_delivered) < 100) {
			if (frappe.datetime.get_diff(doc.delivery_date) < 0) {
				// not delivered & overdue
				return [
					__("Overdue"),
					"red",
					"per_delivered,<,100|delivery_date,<,Today|status,!=,Closed|docstatus,=,1",
				];
			} else if (flt(doc.grand_total) === 0) {
				// not delivered (zeroount order)
				return [
					__("To Deliver"),
					"orange",
					"per_delivered,<,100|grand_total,=,0|status,!=,Closed|docstatus,=,1",
				];
			} else if (flt(doc.per_billed) < 100) {
				// not delivered & not billed
				return [
					__("To Deliver and Bill"),
					"orange",
					"per_delivered,<,100|per_billed,<,100|status,!=,Closed",
				];
			} else {
				// not billed
				return [__("To Deliver"), "orange", "per_delivered,<,100|per_billed,=,100|status,!=,Closed"];
			}
		} else if (
			flt(doc.per_delivered) === 100 &&
			flt(doc.grand_total) !== 0 &&
			flt(doc.per_billed) < 100
		) {
			// to bill
			return [__("To Bill"), "orange", "per_delivered,=,100|per_billed,<,100|status,!=,Closed"];
		} else if (doc.skip_delivery_note && flt(doc.per_billed) < 100) {
			return [__("To Bill"), "orange", "per_billed,<,100|status,!=,Closed"];
		}
	},
	onload: function (listview) {
		var method = "erpnext.selling.doctype.sales_order.sales_order.close_or_unclose_sales_orders";

		listview.page.add_menu_item(__("Close"), function () {
			listview.call_for_selected_items(method, { status: "Closed" });
		});

		listview.page.add_menu_item(__("Re-open"), function () {
			listview.call_for_selected_items(method, { status: "Submitted" });
		});

		// ── Client Script: "Auto Share with Sales Team" / "Sales Status in List view" ──
		listview.page.add_actions_menu_item(__('Share with Sales Team Users'), async function () {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.msgprint(__('Please select at least one Sales Order.'));
				return;
			}

			frappe.confirm(
				__('Share {0} selected Sales Orders with assigned and parent sales persons?', [selected.length]),
				async () => {
					for (const so of selected) {
						await _share_sales_order_with_users_list(so.name);
					}
					frappe.msgprint(__('Sharing complete.'));
				}
			);
		});

		if (frappe.model.can_create("Sales Invoice")) {
			listview.page.add_action_item(__("Sales Invoice"), () => {
				erpnext.bulk_transaction_processing.create(listview, "Sales Order", "Sales Invoice");
			});
		}

		if (frappe.model.can_create("Delivery Note")) {
			listview.page.add_action_item(__("Delivery Note"), () => {
				erpnext.bulk_transaction_processing.create(listview, "Sales Order", "Delivery Note");
			});
		}

		if (frappe.model.can_create("Payment Entry")) {
			listview.page.add_action_item(__("Advance Payment"), () => {
				erpnext.bulk_transaction_processing.create(listview, "Sales Order", "Payment Entry");
			});
		}
	},
};

// ── Client Script: "Auto Share with Sales Team" ──
async function _share_sales_order_with_users_list(sales_order_name) {
	try {
		const { message: doc } = await frappe.call({
			method: "frappe.client.get",
			args: { doctype: "Sales Order", name: sales_order_name }
		});

		if (!doc.sales_team || doc.sales_team.length === 0) return;

		const salesPersons = doc.sales_team.map(row => row.sales_person).filter(Boolean);
		const allSalesPersons = new Set(salesPersons);

		await Promise.all(salesPersons.map(async sp => {
			const res = await frappe.db.get_value('Sales Person', sp, 'parent_sales_person');
			const parent = res && res.message && res.message.parent_sales_person;
			if (parent) allSalesPersons.add(parent);
		}));

		const res = await frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "User Permission",
				filters: {
					allow: "Sales Person",
					for_value: ["in", Array.from(allSalesPersons)]
				},
				fields: ["user"],
				limit_page_length: 1000
			}
		});

		if (!res.message || res.message.length === 0) return;

		const users = [...new Set(res.message.map(r => r.user))];

		for (const user of users) {
			let alreadyShared = false;
			try {
				const existing = await frappe.call({
					method: "frappe.client.get_list",
					args: {
						doctype: "DocShare",
						filters: {
							user: user,
							share_doctype: "Sales Order",
							share_name: sales_order_name
						},
						fields: ["name"],
						limit_page_length: 1
					}
				});
				alreadyShared = existing.message && existing.message.length > 0;
			} catch (e) {
				alreadyShared = false;
			}

			if (!alreadyShared) {
				await frappe.call({
					method: "frappe.client.insert",
					args: {
						doc: {
							doctype: "DocShare",
							user: user,
							share_doctype: "Sales Order",
							share_name: sales_order_name,
							read: 1,
							write: 1,
							share: 1,
							submit: 1
						}
					}
				});
			}
		}
	} catch (err) {
		console.error("Error sharing " + sales_order_name + ":", err);
	}
}
