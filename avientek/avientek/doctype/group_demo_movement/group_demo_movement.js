frappe.ui.form.on("Group Demo Movement", {
	refresh(frm) {
		frm.trigger("set_status_color");
		frm.trigger("movement_type");

		if (frm.doc.docstatus === 1 && frm.doc.movement_type === "Group Move Out") {
			// Show "Group Return" button if any assets still out
			const has_open = (frm.doc.assets || []).some(row => {
				if (!row.demo_movement) return false;
				return true; // We check status server-side
			});

			if (has_open && frm.doc.status !== "Returned" && frm.doc.status !== "Completed") {
				frm.add_custom_button(__("Group Return All"), () => {
					frappe.confirm(
						__("Create a Group Return for all assets in this movement?"),
						() => {
							frappe.new_doc("Group Demo Movement", {
								movement_type: "Group Return",
								company: frm.doc.company,
								customer: frm.doc.customer,
								contact_person: frm.doc.contact_person,
								mobile: frm.doc.mobile,
								email: frm.doc.email,
								country: frm.doc.country,
								purpose: frm.doc.purpose,
								requested_salesperson: frm.doc.requested_salesperson,
							});
						}
					);
				}, __("Actions"));
			}

			frm.add_custom_button(__("Print Group Acknowledgement"), () => {
				frappe.set_route("print", "Group Demo Movement", frm.doc.name);
			}, __("Print"));
		}
	},

	movement_type(frm) {
		const is_out = frm.doc.movement_type === "Group Move Out";
		frm.toggle_reqd("expected_return_date", is_out);

		// Relabel Movement Date for Return
		if (frm.doc.movement_type === "Group Return") {
			frm.fields_dict.movement_date.set_label(__("Return Date"));
		} else {
			frm.fields_dict.movement_date.set_label(__("Movement Date"));
		}

		// Update asset query based on movement type
		if (frm.doc.movement_type === "Group Return") {
			frm.set_query("asset", "assets", () => ({
				filters: {
					custom_is_demo_asset: 1,
					custom_dam_status: ["in", ["On Demo", "Issued as Standby"]],
					docstatus: ["!=", 2],
				},
			}));
		} else {
			frm.set_query("asset", "assets", () => ({
				filters: {
					custom_is_demo_asset: 1,
					custom_dam_status: "Free",
					docstatus: ["!=", 2],
				},
			}));
		}
	},

	set_status_color(frm) {
		const color_map = {
			"Draft": "gray",
			"Open": "orange",
			"Partially Returned": "blue",
			"Returned": "green",
			"Completed": "green",
			"Cancelled": "red",
		};
		const color = color_map[frm.doc.status] || "gray";
		if (frm.doc.status) frm.page.set_indicator(frm.doc.status, color);
	},
});

frappe.ui.form.on("Group Demo Movement Asset", {
	asset(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.asset) return;

		frappe.db.get_value("Asset", row.asset, [
			"asset_name", "item_code", "company", "custom_dam_status", "custom_serial_no"
		], (r) => {
			if (!r) return;
			frappe.model.set_value(cdt, cdn, {
				asset_name: r.asset_name,
				item_code: r.item_code,
				company: r.company,
				serial_number: r.custom_serial_no || "",
				asset_status: r.custom_dam_status || "Free",
			});

			// Fetch brand from Item
			if (r.item_code) {
				frappe.db.get_value("Item", r.item_code, "brand", (item) => {
					if (item && item.brand) {
						frappe.model.set_value(cdt, cdn, "brand", item.brand);
					}
				});
			}

			// Warn if asset not available for Move Out
			if (frm.doc.movement_type === "Group Move Out" && r.custom_dam_status && r.custom_dam_status !== "Free") {
				frappe.msgprint({
					title: __("Asset Not Available"),
					message: __("Asset {0} ({1}) is currently <b>{2}</b>. Only Free assets can be moved out.", [
						row.asset, r.asset_name, r.custom_dam_status
					]),
					indicator: "orange",
				});
			}
		});
	},
});
