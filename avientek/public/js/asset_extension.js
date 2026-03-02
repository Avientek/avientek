frappe.ui.form.on("Asset", {
	refresh(frm) {
		_set_dam_indicator(frm);

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
				frappe.new_doc("Demo Movement", {
					asset: frm.doc.name,
					movement_type: "Return",
					company: frm.doc.company,
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

	const color_map = {
		"Free": "green",
		"On Demo": "orange",
		"Issued as Standby": "blue",
	};
	const status = frm.doc.custom_dam_status || "Free";
	frm.page.set_indicator(__(status), color_map[status] || "gray");
}
