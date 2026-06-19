// ── Avientek List View customization for Delivery Note ──
// Jithin 2026-06-19: voided Drafts should appear visually distinct
// in the list view (red "Cancelled (Voided)" indicator) instead of
// the standard orange "Draft" badge.
//
// Load-order note: Frappe loads doctype_list_js hook files (including
// this one) BEFORE the auto-discovered <app>/<module>/doctype/<dt>/
// <dt>_list.js (where ERPNext's delivery_note_list.js lives). If we
// just set frappe.listview_settings["Delivery Note"] at top level,
// ERPNext's file wipes ours wholesale a moment later.
//
// Fix: defer the override to the next tick via setTimeout. By then
// ERPNext has set its listview_settings, and we mutate get_indicator
// + extend add_fields without replacing the whole object — preserving
// ERPNext's onload (Delivery Trip / Sales Invoice / Packing Slip
// bulk actions) and its other indicator branches.
(function () {
	const apply_void_indicator = function () {
		const settings = frappe.listview_settings["Delivery Note"] || {};

		// Ensure custom_is_void is fetched alongside ERPNext's standard fields.
		const fields = settings.add_fields || [];
		if (fields.indexOf("custom_is_void") === -1) {
			fields.push("custom_is_void");
		}
		settings.add_fields = fields;

		// Wrap ERPNext's get_indicator: void branch first, then fall
		// through to whatever ERPNext returns.
		const prev_get_indicator = settings.get_indicator;
		settings.get_indicator = function (doc) {
			if (doc.docstatus === 0 && cint(doc.custom_is_void)) {
				return [__("Cancelled (Voided)"), "red", "custom_is_void,=,1"];
			}
			if (prev_get_indicator) {
				return prev_get_indicator(doc);
			}
		};

		frappe.listview_settings["Delivery Note"] = settings;
	};

	// Defer one tick — ERPNext's wholesale-replace runs synchronously
	// later in the same JS load cycle; setTimeout puts us after it.
	setTimeout(apply_void_indicator, 0);

	// And re-apply on every list view route in case ERPNext re-sets
	// the object on navigation (defensive — runs cheaply).
	$(document).on("page-change", function () {
		setTimeout(apply_void_indicator, 0);
	});
})();
