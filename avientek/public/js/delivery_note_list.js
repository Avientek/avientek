// ── Avientek List View customization for Delivery Note ──
// Jithin 2026-06-19: voided Drafts should appear visually distinct
// in the list view (red "Cancelled (Voided)" indicator) instead of
// the standard orange "Draft" badge.
//
// PRODUCTION-READY DESIGN
//
// The badge text on the list view is controlled by three layers
// (any one can win). After much debugging, we use a layered
// defense so SOMETHING is always correct:
//
//   1. Server-side: avientek.events.delivery_note.validate_void_state
//      forces doc.status="Cancelled" when custom_is_void=1. Frappe's
//      default indicator color map paints "Cancelled" red. This
//      handles any code path that renders status directly.
//
//   2. Custom Field: custom_is_void.in_list_view=1 so the list query
//      always SELECTs it. Combined with the Voided standard filter,
//      users can drill into voided DNs in one click.
//
//   3. Client-side (this file): patches both
//      frappe.listview_settings["Delivery Note"].get_indicator AND
//      cur_list.listview_settings.get_indicator (snapshot) on every
//      route change. Returns ["Cancelled (Voided)", "red"] for
//      voided drafts, so the row dot indicator shows correctly.
//
// We deliberately do NOT call cur_list.refresh(true) here — that
// triggers ListView.toggle_result_area which crashes with
// "Cannot read properties of undefined (reading 'toggle')" if the
// result area DOM isn't fully built yet. Next natural refresh
// picks up the new indicator function.
(function () {
	const DT = "Delivery Note";

	const apply_void_indicator = function () {
		const settings = frappe.listview_settings[DT] || {};

		// Ensure custom_is_void is fetched.
		const fields = settings.add_fields || [];
		if (fields.indexOf("custom_is_void") === -1) {
			fields.push("custom_is_void");
			settings.add_fields = fields;
		}

		// ROOT-CAUSE FIX (2026-06-19): Frappe v15
		// frappe/public/js/frappe/model/indicator.js:72-74 hard-codes a
		// fast-path that returns "Draft" for any submittable doctype
		// with docstatus=0 — BEFORE settings.get_indicator runs. The
		// only way to bypass it is `has_indicator_for_draft = true`,
		// which signals "I have my own Draft logic, skip the
		// shortcut." With this flag set, Frappe falls through to:
		//   - line 82-86: doc.status vs meta.states (our server-side
		//     status="Cancelled" matches the DN "Cancelled" state →
		//     red pill, label "Cancelled", filter status,=,Cancelled).
		//   - line 88-91: settings.get_indicator as final fallback.
		// Without this flag, no client-side override of the Draft pill
		// is possible.
		settings.has_indicator_for_draft = true;

		// Wrap get_indicator if not already wrapped. This now actually
		// runs (was dead code before has_indicator_for_draft).
		if (!settings.__avientek_void_patched) {
			const prev = settings.get_indicator;
			settings.get_indicator = function (doc) {
				if (cint(doc.docstatus) === 0 && cint(doc.custom_is_void)) {
					return [__("Cancelled (Voided)"), "red", "custom_is_void,=,1"];
				}
				if (prev) return prev(doc);
			};
			settings.__avientek_void_patched = true;
		}
		frappe.listview_settings[DT] = settings;

		// Also patch the live snapshot if a list instance is already
		// mounted (snapshot captured at construction time, before this
		// code runs).
		try {
			if (
				typeof cur_list !== "undefined" &&
				cur_list &&
				cur_list.doctype === DT
			) {
				cur_list.listview_settings = settings;
			}
		} catch (e) { /* cur_list may not exist yet */ }
	};

	// Apply at load, after a tick, and on every route change.
	apply_void_indicator();
	setTimeout(apply_void_indicator, 0);
	setTimeout(apply_void_indicator, 250);

	if (frappe.router && frappe.router.on) {
		frappe.router.on("change", function () {
			const route = frappe.get_route ? frappe.get_route() : [];
			if (route && route[0] === "List" && route[1] === DT) {
				setTimeout(apply_void_indicator, 0);
				setTimeout(apply_void_indicator, 250);
			}
		});
	}

	$(document).on("page-change", function () {
		setTimeout(apply_void_indicator, 0);
	});
})();
