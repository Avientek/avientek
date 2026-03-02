frappe.ui.form.on("Demo Movement", {
	refresh(frm) {
		frm.trigger("set_status_color");
		if (frm.doc.docstatus === 1 && frm.doc.movement_type === "Move Out" && frm.doc.status !== "Returned") {
			frm.add_custom_button(__("Print Acknowledgement"), () => {
				frappe.set_route("print", "Demo Movement", frm.doc.name, {
					print_format: "Customer Acknowledgement",
				});
			}, __("Print"));
		}
	},

	demo_asset(frm) {
		if (!frm.doc.demo_asset) return;
		frappe.db.get_value("Demo Asset", frm.doc.demo_asset, [
			"serial_number", "company", "brand", "model", "part_number", "status"
		], (r) => {
			if (!r) return;
			frm.set_value("serial_number", r.serial_number);
			frm.set_value("company", r.company);

			// Warn if asset is not Free when moving out
			if (frm.doc.movement_type === "Move Out" && r.status !== "Free") {
				frappe.msgprint({
					title: __("Asset Not Available"),
					message: __("This demo asset is currently <b>{0}</b>. Only Free assets can be moved out.", [r.status]),
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
