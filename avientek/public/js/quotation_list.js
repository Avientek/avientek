frappe.listview_settings["Quotation"] = {
	add_fields: ["customer_name", "base_grand_total", "status", "company", "currency", "valid_till"],

	onload: function (listview) {
		if (listview.page.fields_dict.quotation_to) {
			listview.page.fields_dict.quotation_to.get_query = function () {
				return {
					filters: {
						name: ["in", ["Customer", "Prospect", "Lead"]],
					},
				};
			};
		}

		if (frappe.model.can_create("Sales Order")) {
			listview.page.add_action_item(__("Sales Order"), () => {
				erpnext.bulk_transaction_processing.create(listview, "Quotation", "Sales Order");
			});
		}

		if (frappe.model.can_create("Sales Invoice")) {
			listview.page.add_action_item(__("Sales Invoice"), () => {
				erpnext.bulk_transaction_processing.create(listview, "Quotation", "Sales Invoice");
			});
		}

		// ── Brand-restricted user: intercept clicks ──
		setup_brand_restricted_click(listview);
	},

	get_indicator: function (doc) {
		if (doc.status === "Open") {
			return [__("Open"), "orange", "status,=,Open"];
		} else if (doc.status === "Partially Ordered") {
			return [__("Partially Ordered"), "yellow", "status,=,Partially Ordered"];
		} else if (doc.status === "Ordered") {
			return [__("Ordered"), "green", "status,=,Ordered"];
		} else if (doc.status === "Lost") {
			return [__("Lost"), "gray", "status,=,Lost"];
		} else if (doc.status === "Expired") {
			return [__("Expired"), "gray", "status,=,Expired"];
		}
	},
};

function setup_brand_restricted_click(listview) {
	if (frappe.session.user === "Administrator") return;

	frappe.call({
		method: "avientek.api.quotation_access.check_user_has_brand_restriction",
		async: false,
		callback: function (r) {
			if (!r.message) return;

			// Mark globally so report view handler can use it
			frappe._brand_restricted = true;

			// ── List View: override row clicks ──
			listview.$result.off("click", ".list-row, .image-view-header, .file-header");

			listview.$result.on("click", ".list-row", function (e) {
				let $target = $(e.target);
				if (
					$target.hasClass("filterable") ||
					$target.hasClass("select-like") ||
					$target.hasClass("list-row-like") ||
					$target.is(":checkbox") ||
					$target.hasClass("list-row-checkbox")
				) {
					return;
				}
				if (e.ctrlKey || e.metaKey) {
					let $check = $(this).find(".list-row-checkbox");
					$check.prop("checked", !$check.prop("checked"));
					e.preventDefault();
					listview.on_row_checked();
					return;
				}

				e.preventDefault();
				e.stopPropagation();
				let $link = $(this).find(".list-subject a[data-name]");
				let name = $link.attr("data-name");
				if (name) {
					show_permitted_items_popup(name);
				}
				return false;
			});

			listview.$result.on("click", ".list-subject a[data-name]", function (e) {
				e.preventDefault();
				e.stopPropagation();
				let name = $(this).attr("data-name");
				if (name) {
					show_permitted_items_popup(name);
				}
				return false;
			});

			// ── Report View: intercept navigation to Quotation forms ──
			setup_report_view_intercept();
		},
	});
}

function setup_report_view_intercept() {
	// Override frappe.set_route to intercept Quotation form navigation
	if (frappe._original_set_route) return; // already patched

	frappe._original_set_route = frappe.set_route;
	frappe.set_route = function () {
		let args = Array.from(arguments);
		// Detect: frappe.set_route("Form", "Quotation", "QN-...")
		// or frappe.set_route("/app/quotation/QN-...")
		let route_str = args.join("/");

		if (
			frappe._brand_restricted &&
			(
				(args[0] === "Form" && args[1] === "Quotation" && args[2]) ||
				(typeof args[0] === "string" && args[0].match(/^\/?(app\/)?quotation\/QN-/i))
			)
		) {
			let name = args[2] || args[0].split("/").pop();
			show_permitted_items_popup(name);
			return;
		}

		return frappe._original_set_route.apply(frappe, arguments);
	};
}

function show_permitted_items_popup(quotation_name) {
	frappe.call({
		method: "avientek.api.quotation_access.get_permitted_quotation_preview",
		args: { quotation_name: quotation_name },
		freeze: true,
		freeze_message: __("Loading quotation..."),
		callback: function (r) {
			if (!r.message) return;
			let data = r.message;

			if (data.full_access) {
				frappe.set_route("Form", "Quotation", quotation_name);
				return;
			}

			let items = data.permitted_items || [];
			let currency = data.currency || "USD";

			// Build items table
			let rows_html = "";
			items.forEach(function (item) {
				rows_html += `
					<tr>
						<td style="padding:6px 8px;">${item.idx}</td>
						<td style="padding:6px 8px;">${frappe.utils.escape_html(item.item_code)}</td>
						<td style="padding:6px 8px;">${frappe.utils.escape_html(item.item_name || "")}</td>
						<td style="padding:6px 8px;">${frappe.utils.escape_html(item.brand)}</td>
						<td style="padding:6px 8px; text-align:right;">${item.qty}</td>
						<td style="padding:6px 8px; text-align:right;">${format_currency(item.custom_selling_price, currency)}</td>
						<td style="padding:6px 8px; text-align:right;">${format_currency(item.custom_selling_amount, currency)}</td>
					</tr>`;
			});

			let no_items_msg = "";
			if (!items.length) {
				no_items_msg = `<tr><td colspan="7" style="text-align:center; padding:20px; color:#888;">
					No items from your permitted brands in this quotation.
				</td></tr>`;
			}

			let html = `
				<div style="margin-bottom:12px;">
					<div style="display:flex; justify-content:space-between; margin-bottom:8px;">
						<div><strong>Customer:</strong> ${frappe.utils.escape_html(data.customer || "")}</div>
						<div><strong>Date:</strong> ${data.transaction_date || ""}</div>
					</div>
					<div style="display:flex; justify-content:space-between; margin-bottom:8px;">
						<div><strong>Status:</strong> <span class="indicator-pill ${get_status_color(data.status)}">${data.status || ""}</span></div>
						<div><strong>Items:</strong> ${data.permitted_count} of ${data.total_items} visible
							${data.restricted_count ? ' <span style="color:#888;">(' + data.restricted_count + ' restricted)</span>' : ""}
						</div>
					</div>
				</div>
				<div style="max-height:400px; overflow-y:auto;">
					<table class="table table-bordered" style="margin-bottom:0; font-size:12px;">
						<thead style="background:#f7f7f7;">
							<tr>
								<th style="padding:6px 8px; width:35px;">#</th>
								<th style="padding:6px 8px;">Item Code</th>
								<th style="padding:6px 8px;">Item Name</th>
								<th style="padding:6px 8px;">Brand</th>
								<th style="padding:6px 8px; text-align:right;">Qty</th>
								<th style="padding:6px 8px; text-align:right;">Selling Price</th>
								<th style="padding:6px 8px; text-align:right;">Amount</th>
							</tr>
						</thead>
						<tbody>
							${rows_html || no_items_msg}
						</tbody>
						${items.length ? `<tfoot style="background:#f7f7f7; font-weight:bold;">
							<tr>
								<td colspan="6" style="padding:6px 8px; text-align:right;">Your Brands Total:</td>
								<td style="padding:6px 8px; text-align:right;">${format_currency(data.permitted_total, currency)}</td>
							</tr>
						</tfoot>` : ""}
					</table>
				</div>
			`;

			let dlg = new frappe.ui.Dialog({
				title: __("Quotation {0}", [quotation_name]),
				size: "extra-large",
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "preview_html",
						options: html,
					},
				],
			});

			dlg.show();
		},
	});
}

function get_status_color(status) {
	let map = {
		Open: "orange",
		"Partially Ordered": "yellow",
		Ordered: "green",
		Lost: "gray",
		Expired: "gray",
		Draft: "red",
	};
	return map[status] || "blue";
}
