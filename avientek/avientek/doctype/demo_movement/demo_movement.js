frappe.ui.form.on("Demo Movement", {
	refresh(frm) {
		frm.trigger("set_status_color");
		frm.trigger("movement_type");
		if (frm.doc.docstatus === 1 && frm.doc.movement_type === "Move Out" && frm.doc.status !== "Returned") {
			frm.add_custom_button(__("Record Return"), () => {
				frappe.new_doc("Demo Movement", {
					asset: frm.doc.asset,
					serial_number: frm.doc.serial_number,
					movement_type: "Return",
					company: frm.doc.company,
					customer: frm.doc.customer,
					contact_person: frm.doc.contact_person,
					mobile: frm.doc.mobile,
					email: frm.doc.email,
					country: frm.doc.country,
					purpose: frm.doc.purpose,
					requested_salesperson: frm.doc.requested_salesperson,
				});
			}, __("Demo"));

			frm.add_custom_button(__("Print Acknowledgement"), () => {
				frappe.set_route("print", "Demo Movement", frm.doc.name, {
					print_format: "Demo Movement Acknowledgement",
				});
			}, __("Print"));
		}
	},

	movement_type(frm) {
		// Toggle required fields based on movement type
		const is_out = frm.doc.movement_type === "Move Out";
		frm.toggle_reqd("customer", is_out);
		frm.toggle_reqd("contact_person", is_out);
		frm.toggle_reqd("expected_return_date", is_out);

		// Relabel Movement Date for Return
		if (frm.doc.movement_type === "Return") {
			frm.fields_dict.movement_date.set_label(__("Return Date"));
		} else {
			frm.fields_dict.movement_date.set_label(__("Movement Date"));
		}

		// Update asset query based on movement type
		if (frm.doc.movement_type === "Return") {
			frm.set_query("asset", () => ({
				filters: {
					custom_is_demo_asset: 1,
					custom_dam_status: ["in", ["On Demo", "Issued as Standby"]],
					docstatus: ["!=", 2],
				},
			}));
		} else {
			frm.set_query("asset", () => ({
				filters: {
					custom_is_demo_asset: 1,
					custom_dam_status: "Free",
					docstatus: ["!=", 2],
				},
			}));
		}
	},

	asset(frm) {
		if (!frm.doc.asset) return;
		frappe.db.get_value("Asset", frm.doc.asset, [
			"company", "custom_dam_status"
		], (r) => {
			if (!r) return;
			frm.set_value("company", r.company);

			// Warn if asset is not Free when moving out
			if (frm.doc.movement_type === "Move Out" && r.custom_dam_status && r.custom_dam_status !== "Free") {
				frappe.msgprint({
					title: __("Asset Not Available"),
					message: __("This asset is currently <b>{0}</b>. Only Free assets can be moved out.", [r.custom_dam_status]),
					indicator: "orange",
				});
			}
		});
	},

	set_status_color(frm) {
		const color_map = { "Open": "orange", "Returned": "green", "Overdue": "red", "Completed": "green" };
		const color = color_map[frm.doc.status] || "gray";
		if (frm.doc.status) frm.page.set_indicator(frm.doc.status, color);
	},
});
