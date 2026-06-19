// ── Avientek List View customization for Delivery Note ──
// Jithin 2026-06-19: voided Drafts show a red "Cancelled (Voided)"
// indicator in the list view instead of the default orange "Draft"
// badge. The DN stays at docstatus=0 (so the naming series is
// preserved) but is visually + functionally treated as cancelled.
//
// IMPLEMENTATION
//
// Frappe v15's frappe.get_indicator (indicator.js:72-74) hard-codes
// a fast-path that returns ["Draft", "red"] for ANY submittable
// doctype with docstatus=0 BEFORE consulting settings.get_indicator
// or doc.status. The only way to skip it via listview_settings is
// `settings.has_indicator_for_draft = true`. BUT — listview_settings
// is overwritten WHOLESALE by ERPNext's auto-loaded
// stock/doctype/delivery_note/delivery_note_list.js, which loads
// AFTER our hook-registered doctype_list_js. Every prior attempt to
// patch listview_settings raced against ERPNext's overwrite and
// lost.
//
// The bulletproof fix: monkey-patch `frappe.get_indicator` ITSELF.
// The list view calls this function for every row's indicator pill,
// reading frappe.get_indicator off the global at call time — no
// snapshot, no race. Once we wrap the function, EVERY indicator
// query (list view, form toolbar, report view, quick-list widget)
// honors the void state.
(function () {
	if (!frappe.get_indicator || frappe.get_indicator.__avientek_void_wrapped) {
		return;
	}
	const _orig_get_indicator = frappe.get_indicator;

	frappe.get_indicator = function (doc, doctype, show_workflow_state) {
		const dt = doctype || (doc && doc.doctype);
		if (
			dt === "Delivery Note" &&
			doc &&
			cint(doc.docstatus) === 0 &&
			cint(doc.custom_is_void)
		) {
			return [
				__("Cancelled (Voided)"),
				"red",
				"custom_is_void,=,1",
			];
		}
		return _orig_get_indicator.call(this, doc, doctype, show_workflow_state);
	};

	frappe.get_indicator.__avientek_void_wrapped = true;

	// Also ensure custom_is_void is fetched on every list query, so
	// `doc.custom_is_void` is truthy when we read it above. We patch
	// the listview_settings.add_fields on every route change to
	// survive ERPNext's wholesale replace.
	const ensure_field_in_list_query = function () {
		const s = frappe.listview_settings["Delivery Note"] || {};
		const fields = s.add_fields || [];
		if (fields.indexOf("custom_is_void") === -1) {
			fields.push("custom_is_void");
			s.add_fields = fields;
		}
		frappe.listview_settings["Delivery Note"] = s;
	};
	ensure_field_in_list_query();
	setTimeout(ensure_field_in_list_query, 0);
	setTimeout(ensure_field_in_list_query, 250);

	if (frappe.router && frappe.router.on) {
		frappe.router.on("change", function () {
			const route = frappe.get_route ? frappe.get_route() : [];
			if (route && route[0] === "List" && route[1] === "Delivery Note") {
				setTimeout(ensure_field_in_list_query, 0);
				setTimeout(ensure_field_in_list_query, 250);
			}
		});
	}

	$(document).on("page-change", function () {
		setTimeout(ensure_field_in_list_query, 0);
	});
})();
