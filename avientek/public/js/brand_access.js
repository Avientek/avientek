/**
 * Brand-restricted access handler.
 *
 * For users with Brand User Permissions, intercepts navigation to documents
 * that contain items from restricted brands and shows a filtered preview popup.
 *
 * Loaded globally via app_include_js so it works across all doctypes.
 */

(function () {
	// Only intercept doctypes with brand on CHILD item table
	// (where a document can have items from mixed brands, some restricted)
	// Parent-level brand doctypes (Item, Serial No, Item Price) are already
	// filtered at the list level by permission_query_conditions — no intercept needed.
	const BRAND_CHILD_DOCTYPES = [
		"Quotation",
		"Sales Order",
		"Sales Invoice",
		"Delivery Note",
		"POS Invoice",
		"Purchase Order",
		"Purchase Receipt",
		"Purchase Invoice",
		"Material Request",
		"Supplier Quotation",
		"Request for Quotation",
		"Opportunity",
	];

	// URL slug → DocType mapping
	const SLUG_MAP = {};
	BRAND_CHILD_DOCTYPES.forEach(function (dt) {
		SLUG_MAP[frappe.router.slug(dt)] = dt;
	});

	// Check brand restriction once per session
	let _checked = false;
	let _restricted = false;

	function check_restriction(callback) {
		if (_checked) {
			callback(_restricted);
			return;
		}
		if (frappe.session.user === "Administrator") {
			_checked = true;
			_restricted = false;
			callback(false);
			return;
		}
		frappe.call({
			method: "avientek.api.quotation_access.check_user_has_brand_restriction",
			async: false,
			callback: function (r) {
				_checked = true;
				_restricted = r.message ? true : false;
				callback(_restricted);
			},
		});
	}

	// ── Override frappe.set_route to intercept form navigation ──
	var _original_set_route = null;

	function setup_route_intercept() {
		if (frappe._brand_route_patched) return;
		frappe._brand_route_patched = true;

		_original_set_route = frappe.set_route;
		frappe.set_route = function () {
			let args = Array.from(arguments);

			// frappe.set_route("Form", "Quotation", "QN-xxx")
			if (args[0] === "Form" && args[2] && BRAND_CHILD_DOCTYPES.includes(args[1])) {
				let name = args[2];
				// Allow new document creation
				if (name.startsWith("new-")) {
					return _original_set_route.apply(frappe, arguments);
				}
				show_brand_preview(args[1], name);
				return;
			}

			// frappe.set_route("/app/quotation/QN-xxx")
			if (typeof args[0] === "string") {
				let path = args[0].replace(/^\/?(app\/)?/, "");
				let parts = path.split("/");
				if (parts.length >= 2) {
					let slug = parts[0];
					let name = parts.slice(1).join("/");
					let dt = SLUG_MAP[slug];
					if (dt && name && !name.startsWith("new-")) {
						show_brand_preview(dt, name);
						return;
					}
				}
			}

			return _original_set_route.apply(frappe, arguments);
		};
	}

	// ── Show permitted items popup ──
	function show_brand_preview(doctype, docname) {
		frappe.call({
			method: "avientek.api.quotation_access.get_permitted_doc_preview",
			args: { doctype: doctype, docname: docname },
			freeze: true,
			freeze_message: __("Loading..."),
			callback: function (r) {
				if (!r.message) return;
				let data = r.message;

				if (data.full_access) {
					// No restriction — navigate using original (unpatched) set_route
					_original_set_route("Form", doctype, docname);
					return;
				}

				// Parent-level brand restriction (Item, Serial No)
				if (data.restricted) {
					frappe.msgprint({
						title: __("Access Restricted"),
						message: data.message,
						indicator: "red",
					});
					return;
				}

				// Child-item level — show filtered preview
				let items = data.permitted_items || [];
				let currency = data.currency || "USD";

				let rows_html = "";
				items.forEach(function (item) {
					rows_html +=
						"<tr>" +
						'<td style="padding:6px 8px;">' + item.idx + "</td>" +
						'<td style="padding:6px 8px;">' + frappe.utils.escape_html(item.item_code) + "</td>" +
						'<td style="padding:6px 8px;">' + frappe.utils.escape_html(item.item_name || "") + "</td>" +
						'<td style="padding:6px 8px;">' + frappe.utils.escape_html(item.brand) + "</td>" +
						'<td style="padding:6px 8px; text-align:right;">' + item.qty + "</td>" +
						'<td style="padding:6px 8px; text-align:right;">' + format_currency(item.rate, currency) + "</td>" +
						'<td style="padding:6px 8px; text-align:right;">' + format_currency(item.amount, currency) + "</td>" +
						"</tr>";
				});

				let no_items = "";
				if (!items.length) {
					no_items =
						'<tr><td colspan="7" style="text-align:center; padding:20px; color:#888;">' +
						"No items from your permitted brands in this document." +
						"</td></tr>";
				}

				let status_color = {
					Open: "orange", Draft: "red", "Partially Ordered": "yellow",
					Ordered: "green", Lost: "gray", Expired: "gray",
					Submitted: "blue", Approved: "green", Cancelled: "gray",
				}[data.status] || "blue";

				let html =
					'<div style="margin-bottom:12px;">' +
					'<div style="display:flex; justify-content:space-between; margin-bottom:8px;">' +
					"<div><strong>Party:</strong> " + frappe.utils.escape_html(data.party || "") + "</div>" +
					"<div><strong>Date:</strong> " + (data.transaction_date || "") + "</div>" +
					"</div>" +
					'<div style="display:flex; justify-content:space-between; margin-bottom:8px;">' +
					'<div><strong>Status:</strong> <span class="indicator-pill ' + status_color + '">' + (data.status || "") + "</span></div>" +
					"<div><strong>Items:</strong> " + data.permitted_count + " of " + data.total_items + " visible" +
					(data.restricted_count ? ' <span style="color:#888;">(' + data.restricted_count + " restricted)</span>" : "") +
					"</div></div></div>" +
					'<div style="max-height:400px; overflow-y:auto;">' +
					'<table class="table table-bordered" style="margin-bottom:0; font-size:12px;">' +
					'<thead style="background:#f7f7f7;"><tr>' +
					'<th style="padding:6px 8px; width:35px;">#</th>' +
					'<th style="padding:6px 8px;">Item Code</th>' +
					'<th style="padding:6px 8px;">Item Name</th>' +
					'<th style="padding:6px 8px;">Brand</th>' +
					'<th style="padding:6px 8px; text-align:right;">Qty</th>' +
					'<th style="padding:6px 8px; text-align:right;">Rate</th>' +
					'<th style="padding:6px 8px; text-align:right;">Amount</th>' +
					"</tr></thead><tbody>" +
					(rows_html || no_items) +
					"</tbody>" +
					(items.length
						? '<tfoot style="background:#f7f7f7; font-weight:bold;"><tr>' +
						  '<td colspan="6" style="padding:6px 8px; text-align:right;">Your Brands Total:</td>' +
						  '<td style="padding:6px 8px; text-align:right;">' + format_currency(data.permitted_amount, currency) + "</td>" +
						  "</tr></tfoot>"
						: "") +
					"</table></div>";

				let dlg = new frappe.ui.Dialog({
					title: __(doctype) + ": " + docname,
					size: "extra-large",
					fields: [{ fieldtype: "HTML", fieldname: "preview_html", options: html }],
				});
				dlg.show();
			},
		});
	}

	// ── Initialize on page ready ──
	$(document).ready(function () {
		check_restriction(function (is_restricted) {
			if (!is_restricted) return;
			setup_route_intercept();
		});
	});

	// Make show_brand_preview available globally for list view handlers
	window.show_brand_preview = show_brand_preview;
})();
