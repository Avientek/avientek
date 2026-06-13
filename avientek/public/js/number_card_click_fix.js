// Number Card click → list view filter passthrough fix.
//
// Sridhar 2026-06-13 via WhatsApp: clicking dashboard number cards
// (APPROVAL PENDING-PO, APPROVAL PENDING-SO, PRF PENDING *, etc.)
// navigated to the doctype's List View but with NO filter applied —
// even though the card's COUNT was computed correctly from the same
// filters_json.
//
// Root cause: Frappe's stock click handler
// (number_card_widget.js:72 set_route()) calls:
//
//     frappe.route_options = { "Purchase Order.workflow_state": ["in", [array]] };
//     frappe.set_route("purchase-order");
//
// Two problems with that call:
//
//   1. `frappe.set_route("purchase-order")` (bare doctype slug, no
//      `/view/list` suffix) is ambiguous. When the user is already on
//      a workspace whose name matches the slug semantics, the router
//      sometimes resolves it as "do nothing" or routes back into the
//      same workspace — `before_refresh()` on the list view never
//      fires, so frappe.route_options is never consumed.
//
//   2. Even when the navigation works, frappe.route_options is
//      JS-memory only — refresh / share-URL drops the filter.
//
// Fix here: intercept NumberCardWidget.set_route() and:
//
//   - Route to the explicit `{slug}/view/list` view path so the list
//     view definitely (re)mounts and consumes filters.
//   - ALSO encode each filter into URL query params so the filter
//     survives refresh, browser-back, share-link, and any
//     route_options timing race. List view's
//     parse_filters_from_route_options() (list_view.js:2130) reads
//     URLSearchParams first and frappe.route_options second; we
//     populate BOTH for belt-and-suspenders.
//
// Custom and Report cards keep their upstream behaviour untouched.

(function () {
	"use strict";

	function _wait_for_widget(retries) {
		if (
			!window.frappe ||
			!frappe.widget ||
			!frappe.widget.NumberCardWidget ||
			!frappe.widget.NumberCardWidget.prototype
		) {
			if ((retries || 0) >= 50) return; // ~10s ceiling
			return setTimeout(_wait_for_widget.bind(null, (retries || 0) + 1), 200);
		}
		_install_override();
	}

	function _install_override() {
		if (frappe._avtk_number_card_patched) return;
		frappe._avtk_number_card_patched = true;

		const _orig_set_route = frappe.widget.NumberCardWidget.prototype.set_route;

		frappe.widget.NumberCardWidget.prototype.set_route = function () {
			try {
				const card_doc = this.card_doc || {};
				const card_type = card_doc.type;

				// Custom + Report cards: leave upstream alone (different
				// route shape; no filters_json to translate).
				if (card_type === "Custom" || card_type === "Report") {
					return _orig_set_route.call(this);
				}

				const doctype = card_doc.document_type;
				if (!doctype) return _orig_set_route.call(this);

				// get_filters() returns the resolved filter array from
				// filters_json — same shape Frappe's count query uses.
				const filters =
					(this.get_filters && this.get_filters()) || [];

				const slug = frappe.router.slug(doctype);
				const route = `${slug}/view/list`;

				// Build BOTH URL query params AND frappe.route_options
				// so the filter survives every code path.
				const params = new URLSearchParams();
				const route_options = {};
				for (let i = 0; i < filters.length; i++) {
					const f = filters[i] || [];
					// Stock shape: [doctype, field, op, value, hidden?]
					const field = f[1];
					const op = f[2];
					const val = f[3];
					if (!field) continue;

					// list_view.js:2147 — when a URL query value is a
					// string starting with `[` and ending with `]`,
					// list view JSON.parses it as ["op", value]. That's
					// exactly the format we emit here.
					const url_payload = JSON.stringify([op, val]);
					params.set(field, url_payload);

					// frappe.route_options (JS memory) — list_view.js:2138
					// also accepts the [op, value] array form keyed by
					// "DocType.field".
					route_options[`${f[0] || doctype}.${field}`] = [op, val];
				}

				frappe.route_options = route_options;

				const qs = params.toString();
				const final_route = qs ? `${route}?${qs}` : route;

				// frappe.set_route with a string-with-? gets routed to
				// `/app/<final_route>` and the list view's
				// parse_filters_from_route_options reads
				// window.location.search.
				frappe.set_route(final_route);
			} catch (e) {
				// Never let our patch break upstream — fall back to the
				// stock behaviour on any unexpected card shape.
				console.warn("[avientek] number-card filter passthrough fell back:", e);
				return _orig_set_route.call(this);
			}
		};
	}

	_wait_for_widget(0);
})();
