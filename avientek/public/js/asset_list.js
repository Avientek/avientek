frappe.listview_settings["Asset"] = frappe.listview_settings["Asset"] || {};

// Fetch DAM fields in list query
const _existing_fields = frappe.listview_settings["Asset"].add_fields || [];
frappe.listview_settings["Asset"].add_fields = [
	..._existing_fields,
	"custom_is_demo_asset",
	"custom_dam_status",
];

// Override status indicator for demo assets
const _orig_indicator = frappe.listview_settings["Asset"].get_indicator;
frappe.listview_settings["Asset"].get_indicator = function (doc) {
	if (doc.custom_is_demo_asset) {
		const color_map = {
			"Free": "green",
			"On Demo": "orange",
			"Issued as Standby": "blue",
		};
		const status = doc.custom_dam_status || "Free";
		return [__(status), color_map[status] || "gray", `custom_dam_status,=,${status}`];
	}
	if (_orig_indicator) return _orig_indicator(doc);
};
