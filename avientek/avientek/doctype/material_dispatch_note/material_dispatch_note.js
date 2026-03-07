frappe.ui.form.on("Material Dispatch Note", {

	refresh(frm) {
		frm.trigger("set_status_indicator");
		if (!frm.is_new() && frm.doc.docstatus === 1) {
			frm.trigger("add_delivery_button");
		}
	},

	sales_order(frm) {
		if (!frm.doc.sales_order) return;
		frappe.db.get_value("Sales Order", frm.doc.sales_order, [
			"customer", "contact_person", "company", "territory",
		], (r) => {
			if (!r) return;
			if (r.customer) frm.set_value("customer", r.customer);
			if (r.company) frm.set_value("company", r.company);
		});
	},

	set_status_indicator(frm) {
		const color_map = {
			"Draft": "gray",
			"Dispatched": "blue",
			"In Transit": "yellow",
			"Delivered": "green",
			"Cancelled": "red",
		};
		frm.page.set_indicator(frm.doc.status, color_map[frm.doc.status] || "gray");
	},

	add_delivery_button(frm) {
		if (frm.doc.status === "Dispatched" || frm.doc.status === "In Transit") {
			frm.add_custom_button(__("Mark as Delivered"), () => {
				frappe.confirm(__("Confirm delivery of this dispatch?"), () => {
					frappe.db.set_value(
						"Material Dispatch Note", frm.doc.name,
						{ status: "Delivered", actual_delivery_date: frappe.datetime.get_today() }
					).then(() => {
						frm.reload_doc();
						frappe.show_alert({ message: __("Marked as Delivered"), indicator: "green" });
					});
				});
			}, __("Actions"));

			if (frm.doc.status === "Dispatched") {
				frm.add_custom_button(__("Mark In Transit"), () => {
					frappe.db.set_value("Material Dispatch Note", frm.doc.name, "status", "In Transit")
						.then(() => frm.reload_doc());
				}, __("Actions"));
			}
		}
	},
});
