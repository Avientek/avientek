frappe.listview_settings["Demo Movement"] = {
	get_indicator(doc) {
		const color_map = {
			"Open": "orange",
			"Overdue": "red",
			"Returned": "green",
			"Completed": "green",
			"Cancelled": "red",
		};
		if (doc.docstatus === 2) {
			return [__("Cancelled"), "red", "status,=,Cancelled"];
		}
		if (doc.status && color_map[doc.status]) {
			return [__(doc.status), color_map[doc.status], "status,=," + doc.status];
		}
	},
};
