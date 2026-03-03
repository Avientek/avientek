frappe.ui.form.on("Demo Movement", {
	refresh(frm) {
		frm.trigger("set_status_color");
		if (frm.doc.docstatus === 1 && frm.doc.movement_type === "Move Out" && frm.doc.status !== "Returned") {
			frm.add_custom_button(__("Record Return"), () => {
				frappe.new_doc("Demo Movement", {
					asset: frm.doc.asset,
					movement_type: "Return",
					company: frm.doc.company,
					customer: frm.doc.customer,
				});
			}, __("Demo"));

			frm.add_custom_button(__("Print Acknowledgement"), () => {
				frappe.set_route("print", "Demo Movement", frm.doc.name, {
					print_format: "Customer Acknowledgement",
				});
			}, __("Print"));
		}

		// Restrict asset field to demo assets only
		frm.set_query("asset", () => ({
			filters: { custom_is_demo_asset: 1 },
		}));
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

	movement_type(frm) {
		// Toggle required fields based on movement type
		const is_out = frm.doc.movement_type === "Move Out";
		frm.toggle_reqd("customer", is_out);
		frm.toggle_reqd("contact_person", is_out);
		frm.toggle_reqd("expected_return_date", is_out);
	},

	set_status_color(frm) {
		const color_map = { "Open": "orange", "Returned": "green", "Overdue": "red" };
		const color = color_map[frm.doc.status] || "gray";
		if (frm.doc.status) frm.page.set_indicator(frm.doc.status, color);
	},
});
