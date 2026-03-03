frappe.ui.form.on("Asset", {
	refresh(frm) {
		_set_dam_indicator(frm);

		// Decapitalize button — available on any submitted asset
		if (!frm.is_new() && frm.doc.docstatus === 1) {
			const decap_statuses = ["Submitted", "Partially Depreciated", "Fully Depreciated"];
			if (decap_statuses.includes(frm.doc.status)) {
				frm.add_custom_button(__("Decapitalize"), () => {
					frappe.new_doc("Asset Decapitalization", {
						asset: frm.doc.name,
					});
				}, __("Manage"));
			}
		}

		if (!frm.doc.custom_is_demo_asset || frm.is_new()) return;

		const status = frm.doc.custom_dam_status || "Free";

		if (status === "Free") {
			frm.add_custom_button(__("Move Out for Demo"), () => {
				frappe.new_doc("Demo Movement", {
					asset: frm.doc.name,
					movement_type: "Move Out",
					company: frm.doc.company,
				});
			}, __("Demo"));
		}

		if (status === "On Demo") {
			frm.add_custom_button(__("Record Return"), () => {
				// Fetch latest open Move Out details to pre-fill Return
				frappe.call({
					method: "frappe.client.get_list",
					args: {
						doctype: "Demo Movement",
						filters: {
							asset: frm.doc.name,
							movement_type: "Move Out",
							status: ["in", ["Open", "Overdue"]],
							docstatus: 1,
						},
						fields: ["name", "customer", "contact_person", "mobile", "email",
							"country", "purpose", "requested_salesperson", "serial_number"],
						order_by: "movement_date desc",
						limit_page_length: 1,
					},
					callback(r) {
						const m = (r.message && r.message[0]) || {};
						frappe.new_doc("Demo Movement", {
							asset: frm.doc.name,
							movement_type: "Return",
							company: frm.doc.company,
							customer: m.customer,
							contact_person: m.contact_person,
							mobile: m.mobile,
							email: m.email,
							country: m.country,
							purpose: m.purpose,
							requested_salesperson: m.requested_salesperson,
							serial_number: m.serial_number,
						});
					},
				});
			}, __("Demo"));
		}

		frm.add_custom_button(__("Demo Movements"), () => {
			frappe.set_route("List", "Demo Movement", { asset: frm.doc.name });
		}, __("Demo"));
	},

	custom_is_demo_asset(frm) {
		_set_dam_indicator(frm);
	},
});

function _set_dam_indicator(frm) {
	if (!frm.doc.custom_is_demo_asset) return;

	// Show ERPNext status for disposed/cancelled assets
	const disposed = ["Scrapped", "Sold", "Capitalized", "Cancelled"];
	if (disposed.includes(frm.doc.status)) {
		frm.page.set_indicator(__(frm.doc.status), "red");
		return;
	}

	const color_map = {
		"Free": "green",
		"On Demo": "orange",
		"Issued as Standby": "blue",
	};
	const status = frm.doc.custom_dam_status || "Free";
	frm.page.set_indicator(__(status), color_map[status] || "gray");
}
