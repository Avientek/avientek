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


// Sridhar 2026-05-29: Frappe v15 picker dialog doesn't honor `report_hide=1`
// on child-table fields. Hide the two broken "Part Number" entries (under
// Items and Service Items sections) from the Pick Columns dialog with a JS
// MutationObserver. The Quotation-parent "Part Number" (first_item_part_number)
// stays visible — it's a separate field on the parent doctype.
(function _hide_broken_part_number_picker_entries() {
	if (window.__avk_pick_columns_observer) return;
	const observer = new MutationObserver(function(mutations) {
		for (const m of mutations) {
			for (const node of m.addedNodes) {
				if (node.nodeType !== 1) continue;
				const el = node.classList && node.classList.contains("modal-dialog")
					? node
					: node.querySelector && node.querySelector(".modal-dialog");
				if (el) _filter_pick_columns(el);
			}
		}
	});
	observer.observe(document.body, { childList: true, subtree: true });
	window.__avk_pick_columns_observer = observer;

	function _filter_pick_columns(modalEl) {
		setTimeout(function() {
			const title = modalEl.querySelector(".modal-title");
			if (!title) return;
			if (title.textContent.trim().toLowerCase().indexOf("pick columns") < 0) return;
			// Only act on Quotation report view. Frappe routes are lowercase
			// ("quotation"), not Title Case — earlier check missed every time.
			const route = (frappe.get_route && frappe.get_route()) || [];
			const onQuotation = route.some(seg =>
				typeof seg === "string" && seg.toLowerCase() === "quotation"
			);
			if (!onQuotation) return;

			// Hide checkbox rows where the section header above contains
			// "(Quotation Item)" AND the label is "Part Number".
			const checkboxes = modalEl.querySelectorAll(".checkbox, .frappe-control[data-fieldtype='Check']");
			checkboxes.forEach(function(cb) {
				const labelEl = cb.querySelector("label") || cb.querySelector(".label-area");
				if (!labelEl) return;
				if (labelEl.textContent.trim() !== "Part Number") return;
				// Walk up to find the nearest preceding heading/section header
				let cur = cb;
				let header = null;
				for (let i = 0; i < 40 && cur; i++) {
					cur = cur.previousElementSibling || (cur.parentElement && cur.parentElement.previousElementSibling) || null;
					if (!cur) break;
					if (cur.tagName === "H6" || cur.tagName === "H5" ||
					    cur.classList.contains("section-head") ||
					    cur.classList.contains("text-muted")) {
						header = cur;
						break;
					}
				}
				if (header && /\(Quotation Item\)/i.test(header.textContent)) {
					cb.style.display = "none";
				}
			});
		}, 100);
	}
})();
