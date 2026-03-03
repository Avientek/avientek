frappe.ui.form.on("RMA Case", {

	refresh(frm) {
		frm.trigger("set_status_indicator");
		frm.trigger("add_action_buttons");

		// Filter asset field to demo assets only (exclude cancelled)
		frm.set_query("demo_asset", () => ({
			filters: { custom_is_demo_asset: 1, docstatus: ["!=", 2] },
		}));
		frm.set_query("standby_unit", () => {
			const filters = { custom_is_demo_asset: 1, docstatus: ["!=", 2], custom_dam_status: "Free" };
			if (frm.doc.demo_asset) filters.name = ["!=", frm.doc.demo_asset];
			return { filters };
		});
	},

	demo_asset(frm) {
		if (!frm.doc.demo_asset) return;
		frappe.db.get_value("Asset", frm.doc.demo_asset, [
			"gross_purchase_amount", "value_after_depreciation", "company",
		], (r) => {
			if (!r) return;
			frm.set_value("gross_asset_value", r.gross_purchase_amount || 0);
			frm.set_value("net_asset_value", r.value_after_depreciation || 0);
			frm.set_value("accumulated_depreciation", (r.gross_purchase_amount || 0) - (r.value_after_depreciation || 0));
			if (r.company && !frm.doc.company) {
				frm.set_value("company", r.company);
			}
		});
	},

	customer(frm) {
		if (frm.doc.customer) {
			frappe.db.get_value("Customer", frm.doc.customer, "default_currency", (r) => {
				if (r && r.default_currency) {
					frm.set_value("repair_cost_currency", r.default_currency);
				}
			});
		}
	},

	set_status_indicator(frm) {
		const color_map = {
			"Open": "orange",
			"In Progress": "blue",
			"Pending Parts": "yellow",
			"Sent for Repair": "purple",
			"Repaired": "cyan",
			"Replaced": "green",
			"Closed": "green",
			"Cancelled": "red",
		};
		const color = color_map[frm.doc.status] || "gray";
		frm.page.set_indicator(frm.doc.status, color);
	},

	add_action_buttons(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 1) return;

		// Issue Standby Unit
		if (!["Closed", "Cancelled"].includes(frm.doc.status) && !frm.doc.standby_unit) {
			frm.add_custom_button(__("Issue Standby Unit"), () => {
				frappe.prompt({
					fieldname: "standby_asset",
					fieldtype: "Link",
					options: "Asset",
					label: __("Asset (Free demo unit to issue as standby)"),
					get_query: () => {
					const filters = { custom_is_demo_asset: 1, docstatus: ["!=", 2], custom_dam_status: "Free" };
					if (frm.doc.demo_asset) filters.name = ["!=", frm.doc.demo_asset];
					return { filters };
				},
					reqd: 1,
				}, (values) => {
					frm.set_value("standby_unit", values.standby_asset);
					frm.save("Update");
					frappe.show_alert({ message: __("Standby unit assigned"), indicator: "green" });
				}, __("Issue Standby Unit"), __("Assign"));
			}, __("Actions"));
		}

		// Return Standby Unit
		if (frm.doc.standby_unit && !["Closed", "Cancelled", "Replaced"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Return Standby Unit"), () => {
				frappe.confirm(
					__("Return standby unit <b>{0}</b>? Its status will be set back to Free.", [frm.doc.standby_unit]),
					() => {
						frm.set_value("standby_unit", "");
						frm.save("Update");
						frappe.show_alert({ message: __("Standby unit returned to Free"), indicator: "green" });
					}
				);
			}, __("Actions"));
		}

		// Mark as Closed
		if (!["Closed", "Cancelled"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Mark as Closed"), () => {
				frappe.confirm(
					__("Close this RMA Case? This will set the status to Closed."),
					() => {
						frm.set_value("status", "Closed");
						frm.save("Update");
					}
				);
			}, __("Actions"));
		}

		// Add Log Entry
		frm.add_custom_button(__("Add Log Entry"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Add Case Log Entry"),
				fields: [
					{
						fieldname: "log_type",
						fieldtype: "Select",
						label: __("Type"),
						options: "Note\nStatus Change\nCustomer Contact\nEngineer Update\nPart Ordered\nRepair Complete\nEscalation",
						default: "Note",
						reqd: 1,
					},
					{
						fieldname: "description",
						fieldtype: "Small Text",
						label: __("Description"),
						reqd: 1,
					},
				],
				primary_action_label: __("Add"),
				primary_action(values) {
					frm.add_child("case_log", {
						log_type: values.log_type,
						description: values.description,
						logged_by: frappe.session.user,
						log_date: frappe.datetime.now_datetime(),
					});
					frm.refresh_field("case_log");
					frm.save("Update");
					d.hide();
					frappe.show_alert({ message: __("Log entry added"), indicator: "green" });
				},
			});
			d.show();
		}, __("Actions"));

		// View related Demo Movements
		if (frm.doc.demo_asset) {
			frm.add_custom_button(__("Demo Movements"), () => {
				frappe.set_route("List", "Demo Movement", { asset: frm.doc.demo_asset });
			}, __("View"));
		}
	},
});
