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

		// Brand-restricted list view click handling
		setup_brand_list_click(listview, "Quotation");
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

/**
 * For brand-restricted users, override list view row clicks
 * to show filtered preview popup instead of navigating to the form.
 */
function setup_brand_list_click(listview, doctype) {
	if (frappe.session.user === "Administrator") return;

	frappe.call({
		method: "avientek.api.quotation_access.check_user_has_brand_restriction",
		async: false,
		callback: function (r) {
			if (!r.message) return;

			// Remove Frappe's default row click handler
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
				if (name && window.show_brand_preview) {
					window.show_brand_preview(doctype, name);
				}
				return false;
			});

			listview.$result.on("click", ".list-subject a[data-name]", function (e) {
				e.preventDefault();
				e.stopPropagation();
				let name = $(this).attr("data-name");
				if (name && window.show_brand_preview) {
					window.show_brand_preview(doctype, name);
				}
				return false;
			});
		},
	});
}
