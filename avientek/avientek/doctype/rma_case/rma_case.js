frappe.ui.form.on("RMA Case", {

	refresh(frm) {
		frm.trigger("set_status_indicator");
		frm.trigger("add_action_buttons");
	},

	demo_asset(frm) {
		if (!frm.doc.demo_asset) return;
		frappe.db.get_value("Demo Asset", frm.doc.demo_asset, [
			"serial_number", "gross_asset_value", "accumulated_depreciation",
			"net_asset_value", "asset_currency", "company",
		], (r) => {
			if (!r) return;
			if (r.serial_number && !frm.doc.asset_serial_number) {
				frm.set_value("asset_serial_number", r.serial_number);
			}
			frm.set_value("gross_asset_value", r.gross_asset_value || 0);
			frm.set_value("accumulated_depreciation", r.accumulated_depreciation || 0);
			frm.set_value("net_asset_value", r.net_asset_value || 0);
			frm.set_value("asset_currency", r.asset_currency);
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
		if (frm.is_new()) return;

		// Issue Standby Unit
		if (frm.doc.status === "In Progress" && !frm.doc.standby_unit) {
			frm.add_custom_button(__("Issue Standby Unit"), () => {
				frappe.prompt({
					fieldname: "demo_asset",
					fieldtype: "Link",
					options: "Demo Asset",
					label: __("Demo Asset (Free unit to issue as standby)"),
					get_query: () => ({ filters: { status: "Free" } }),
					reqd: 1,
				}, (values) => {
					frm.set_value("standby_unit", values.demo_asset);
					frm.save();
					frappe.show_alert({ message: __("Standby unit assigned"), indicator: "green" });
				}, __("Issue Standby Unit"), __("Assign"));
			}, __("Actions"));
		}

		// Return Standby Unit
		if (frm.doc.standby_unit && !["Closed", "Cancelled", "Replaced"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Return Standby Unit"), () => {
				frm.set_value("standby_unit", "");
				frm.save();
				frappe.show_alert({ message: __("Standby unit returned to Free"), indicator: "blue" });
			}, __("Actions"));
		}

		// Mark as Closed
		if (!["Closed", "Cancelled"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Mark as Closed"), () => {
				frappe.confirm(
					__("Close this RMA Case? This will set the status to Closed."),
					() => {
						frm.set_value("status", "Closed");
						frm.save();
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
					frm.save();
					d.hide();
					frappe.show_alert({ message: __("Log entry added"), indicator: "green" });
				},
			});
			d.show();
		}, __("Actions"));

		// View related Demo Movements
		if (frm.doc.demo_asset) {
			frm.add_custom_button(__("Demo Movements"), () => {
				frappe.set_route("List", "Demo Movement", { demo_asset: frm.doc.demo_asset });
			}, __("View"));
		}
	},
});
