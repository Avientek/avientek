// ── Avientek List View customization for Delivery Note ──
// Jithin 2026-06-19: voided Drafts should appear visually distinct
// in the list view (red "Cancelled (Voided)" indicator) instead of
// the standard orange "Draft" badge.
//
// Load-order gotcha that bit us:
//   ERPNext's auto-loaded delivery_note_list.js sets
//   frappe.listview_settings["Delivery Note"] = { ... }
//   AFTER my hook-registered file loads. So if I set get_indicator
//   at top level, ERPNext's wholesale replace wipes it.
//
// Worse: even if I defer with setTimeout(0) so my override survives
// in frappe.listview_settings, the live `cur_list.listview_settings`
// is a STALE SNAPSHOT captured when the ListView was constructed —
// pointing at ERPNext's object BEFORE my override applied. So
// rendering uses Frappe's default Draft indicator, not mine.
//
// Fix: hook into frappe.router.on("change") AND $(document).on
// "page-change". On every navigation to /app/delivery-note, mutate
// BOTH frappe.listview_settings["Delivery Note"] AND
// cur_list.listview_settings (if a list instance is already mounted).
const _patch_dn_listview = function () {
	const settings = frappe.listview_settings["Delivery Note"] || {};
	if (settings.__avientek_void_patched) {
		return; // already done for this navigation
	}
	settings.__avientek_void_patched = true;

	const fields = settings.add_fields || [];
	if (fields.indexOf("custom_is_void") === -1) fields.push("custom_is_void");
	settings.add_fields = fields;

	const prev_get_indicator = settings.get_indicator;
	settings.get_indicator = function (doc) {
		if (cint(doc.docstatus) === 0 && cint(doc.custom_is_void)) {
			return [__("Cancelled (Voided)"), "red", "custom_is_void,=,1"];
		}
		if (prev_get_indicator) return prev_get_indicator(doc);
	};
	frappe.listview_settings["Delivery Note"] = settings;

	// Critical step: if the list view is ALREADY constructed (i.e. user
	// navigated to /app/delivery-note before this code ran), its
	// listview_settings is a stale snapshot. Patch it directly.
	try {
		if (
			typeof cur_list !== "undefined" &&
			cur_list &&
			cur_list.doctype === "Delivery Note"
		) {
			cur_list.listview_settings = settings;
			// Force re-fetch with new add_fields, then re-render.
			cur_list.refresh(true);
		}
	} catch (e) { /* cur_list may be undefined yet */ }
};

// Run as early as possible — before ERPNext's file loads (in case),
// and also after a tick (in case ERPNext already overwrote).
_patch_dn_listview();
setTimeout(_patch_dn_listview, 0);
setTimeout(_patch_dn_listview, 250);

// And on every route change to /app/delivery-note (re-clear our
// __avientek_void_patched flag so we re-run when the listview
// remounts on navigation).
if (frappe.router && frappe.router.on) {
	frappe.router.on("change", function () {
		const route = frappe.get_route ? frappe.get_route() : [];
		if (route && route[0] === "List" && route[1] === "Delivery Note") {
			// Clear the patched flag so we re-apply for the new instance
			const s = frappe.listview_settings["Delivery Note"];
			if (s) delete s.__avientek_void_patched;
			setTimeout(_patch_dn_listview, 0);
			setTimeout(_patch_dn_listview, 250);
		}
	});
}

// Defensive: also patch on jQuery page-change in case router.on
// isn't firing on this Frappe version.
$(document).on("page-change", function () {
	const s = frappe.listview_settings["Delivery Note"];
	if (s) delete s.__avientek_void_patched;
	setTimeout(_patch_dn_listview, 0);
});
