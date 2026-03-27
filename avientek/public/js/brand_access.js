/**
 * Brand, Item Group, Customer Group, Supplier Group & Sales Person restricted access handler.
 *
 * For users with these User Permissions:
 * 1. Intercepts navigation to documents with restricted data → shows filtered popup or blocks access
 * 2. Auto-filters dropdowns in Script Reports to only permitted values
 *
 * Loaded globally via app_include_js.
 */

(function () {
	// Doctypes with brand/item_group on CHILD item table (mixed values possible)
	const RESTRICTED_CHILD_DOCTYPES = [
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
		"Avientek Proforma Invoice",
		"Existing Quotation",
	];

	// URL slug → DocType mapping
	const SLUG_MAP = {};
	RESTRICTED_CHILD_DOCTYPES.forEach(function (dt) {
		SLUG_MAP[frappe.router.slug(dt)] = dt;
	});

	// Cache
	let _brand_checked = false;
	let _brand_restricted = false;
	let _permitted_brands = null;

	let _ig_checked = false;
	let _ig_restricted = false;
	let _permitted_item_groups = null;

	let _cg_checked = false;
	let _cg_restricted = false;
	let _permitted_customer_groups = null;

	let _sg_checked = false;
	let _sg_restricted = false;
	let _permitted_supplier_groups = null;

	let _sp_checked = false;
	let _sp_restricted = false;
	let _permitted_sales_persons = null;

	function check_brand_restriction(callback) {
		if (_brand_checked) {
			callback(_brand_restricted);
			return;
		}
		if (frappe.session.user === "Administrator") {
			_brand_checked = true;
			_brand_restricted = false;
			callback(false);
			return;
		}
		frappe.call({
			method: "avientek.api.quotation_access.check_user_has_brand_restriction",
			async: false,
			callback: function (r) {
				_brand_checked = true;
				_brand_restricted = r.message ? true : false;
				callback(_brand_restricted);
			},
		});
	}

	function check_item_group_restriction(callback) {
		if (_ig_checked) {
			callback(_ig_restricted);
			return;
		}
		if (frappe.session.user === "Administrator") {
			_ig_checked = true;
			_ig_restricted = false;
			callback(false);
			return;
		}
		frappe.call({
			method: "avientek.api.quotation_access.check_user_has_item_group_restriction",
			async: false,
			callback: function (r) {
				_ig_checked = true;
				_ig_restricted = r.message ? true : false;
				callback(_ig_restricted);
			},
		});
	}

	function get_permitted_brands(callback) {
		if (_permitted_brands !== null) {
			callback(_permitted_brands);
			return;
		}
		frappe.call({
			method: "avientek.api.quotation_access.get_permitted_brands",
			async: false,
			callback: function (r) {
				_permitted_brands = r.message || [];
				callback(_permitted_brands);
			},
		});
	}

	function get_permitted_item_groups(callback) {
		if (_permitted_item_groups !== null) {
			callback(_permitted_item_groups);
			return;
		}
		frappe.call({
			method: "avientek.api.quotation_access.get_permitted_item_groups",
			async: false,
			callback: function (r) {
				_permitted_item_groups = r.message || [];
				callback(_permitted_item_groups);
			},
		});
	}

	function check_customer_group_restriction(callback) {
		if (_cg_checked) {
			callback(_cg_restricted);
			return;
		}
		if (frappe.session.user === "Administrator") {
			_cg_checked = true;
			_cg_restricted = false;
			callback(false);
			return;
		}
		frappe.call({
			method: "avientek.api.quotation_access.check_user_has_customer_group_restriction",
			async: false,
			callback: function (r) {
				_cg_checked = true;
				_cg_restricted = r.message ? true : false;
				callback(_cg_restricted);
			},
		});
	}

	function check_supplier_group_restriction(callback) {
		if (_sg_checked) {
			callback(_sg_restricted);
			return;
		}
		if (frappe.session.user === "Administrator") {
			_sg_checked = true;
			_sg_restricted = false;
			callback(false);
			return;
		}
		frappe.call({
			method: "avientek.api.quotation_access.check_user_has_supplier_group_restriction",
			async: false,
			callback: function (r) {
				_sg_checked = true;
				_sg_restricted = r.message ? true : false;
				callback(_sg_restricted);
			},
		});
	}

	function check_sales_person_restriction(callback) {
		if (_sp_checked) {
			callback(_sp_restricted);
			return;
		}
		if (frappe.session.user === "Administrator") {
			_sp_checked = true;
			_sp_restricted = false;
			callback(false);
			return;
		}
		frappe.call({
			method: "avientek.api.quotation_access.check_user_has_sales_person_restriction",
			async: false,
			callback: function (r) {
				_sp_checked = true;
				_sp_restricted = r.message ? true : false;
				callback(_sp_restricted);
			},
		});
	}

	function get_permitted_customer_groups(callback) {
		if (_permitted_customer_groups !== null) {
			callback(_permitted_customer_groups);
			return;
		}
		frappe.call({
			method: "avientek.api.quotation_access.get_permitted_customer_groups",
			async: false,
			callback: function (r) {
				_permitted_customer_groups = r.message || [];
				callback(_permitted_customer_groups);
			},
		});
	}

	function get_permitted_supplier_groups(callback) {
		if (_permitted_supplier_groups !== null) {
			callback(_permitted_supplier_groups);
			return;
		}
		frappe.call({
			method: "avientek.api.quotation_access.get_permitted_supplier_groups",
			async: false,
			callback: function (r) {
				_permitted_supplier_groups = r.message || [];
				callback(_permitted_supplier_groups);
			},
		});
	}

	function get_permitted_sales_persons(callback) {
		if (_permitted_sales_persons !== null) {
			callback(_permitted_sales_persons);
			return;
		}
		frappe.call({
			method: "avientek.api.quotation_access.get_permitted_sales_persons",
			async: false,
			callback: function (r) {
				_permitted_sales_persons = r.message || [];
				callback(_permitted_sales_persons);
			},
		});
	}

	// ── 1. Route intercept for child-item doctypes ──

	var _original_set_route = null;

	function setup_route_intercept() {
		if (frappe._brand_route_patched) return;
		frappe._brand_route_patched = true;

		_original_set_route = frappe.set_route;
		frappe.set_route = function () {
			let args = Array.from(arguments);

			// frappe.set_route("Form", "Quotation", "QN-xxx")
			if (args[0] === "Form" && args[2] && RESTRICTED_CHILD_DOCTYPES.includes(args[1])) {
				let name = args[2];
				if (name.startsWith("new-")) {
					return _original_set_route.apply(frappe, arguments);
				}
				show_restricted_preview(args[1], name);
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
						show_restricted_preview(dt, name);
						return;
					}
				}
			}

			return _original_set_route.apply(frappe, arguments);
		};
	}

	// ── 2. Show permitted items popup ──

	function show_restricted_preview(doctype, docname) {
		frappe.call({
			method: "avientek.api.quotation_access.get_permitted_doc_preview",
			args: { doctype: doctype, docname: docname },
			freeze: true,
			freeze_message: __("Loading..."),
			callback: function (r) {
				if (!r.message) return;
				let data = r.message;

				if (data.full_access) {
					_original_set_route.call(frappe, "Form", doctype, docname);
					return;
				}

				if (data.restricted) {
					frappe.msgprint({
						title: __("Access Restricted"),
						message: data.message,
						indicator: "red",
					});
					return;
				}

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
						'<td style="padding:6px 8px;">' + frappe.utils.escape_html(item.item_group || "") + "</td>" +
						'<td style="padding:6px 8px; text-align:right;">' + item.qty + "</td>" +
						'<td style="padding:6px 8px; text-align:right;">' + format_currency(item.rate, currency) + "</td>" +
						'<td style="padding:6px 8px; text-align:right;">' + format_currency(item.amount, currency) + "</td>" +
						"</tr>";
				});

				let no_items = "";
				if (!items.length) {
					no_items =
						'<tr><td colspan="8" style="text-align:center; padding:20px; color:#888;">' +
						"No items from your permitted brands/item groups in this document." +
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
					'<th style="padding:6px 8px;">Item Group</th>' +
					'<th style="padding:6px 8px; text-align:right;">Qty</th>' +
					'<th style="padding:6px 8px; text-align:right;">Rate</th>' +
					'<th style="padding:6px 8px; text-align:right;">Amount</th>' +
					"</tr></thead><tbody>" +
					(rows_html || no_items) +
					"</tbody>" +
					(items.length
						? '<tfoot style="background:#f7f7f7; font-weight:bold;"><tr>' +
						  '<td colspan="7" style="padding:6px 8px; text-align:right;">Your Total:</td>' +
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

	// ── 3. Auto-filter Brand and Item Group dropdowns in Script Reports ──

	function setup_report_filters() {
		$(document).on("page-change", apply_report_filters);
		setTimeout(apply_report_filters, 1000);
	}

	function apply_report_filters() {
		let route = frappe.get_route();
		if (!route || route[0] !== "query-report") return;

		setTimeout(function () {
			let page = frappe.pages["query-report"];
			if (!page || !page.page) return;

			let qr = frappe.query_report;
			if (!qr || !qr.filters) return;

			// Filter Brand dropdown
			let brand_filter = qr.filters.find(function (f) {
				return f.df && f.df.fieldname === "brand" &&
					f.df.fieldtype === "Link" &&
					f.df.options === "Brand";
			});

			if (brand_filter) {
				get_permitted_brands(function (brands) {
					if (!brands || !brands.length) return;
					brand_filter.df.get_query = function () {
						return { filters: { name: ["in", brands] } };
					};
					if (brands.length === 1 && !brand_filter.get_value()) {
						brand_filter.set_value(brands[0]);
					}
				});
			}

			// Filter Item Group dropdown
			let ig_filter = qr.filters.find(function (f) {
				return f.df && f.df.fieldname === "item_group" &&
					f.df.fieldtype === "Link" &&
					f.df.options === "Item Group";
			});

			if (ig_filter) {
				get_permitted_item_groups(function (item_groups) {
					if (!item_groups || !item_groups.length) return;
					ig_filter.df.get_query = function () {
						return { filters: { name: ["in", item_groups] } };
					};
					if (item_groups.length === 1 && !ig_filter.get_value()) {
						ig_filter.set_value(item_groups[0]);
					}
				});
			}

			// Filter Customer Group dropdown
			let cg_filter = qr.filters.find(function (f) {
				return f.df && f.df.fieldname === "customer_group" &&
					f.df.fieldtype === "Link" &&
					f.df.options === "Customer Group";
			});

			if (cg_filter) {
				get_permitted_customer_groups(function (customer_groups) {
					if (!customer_groups || !customer_groups.length) return;
					cg_filter.df.get_query = function () {
						return { filters: { name: ["in", customer_groups] } };
					};
					if (customer_groups.length === 1 && !cg_filter.get_value()) {
						cg_filter.set_value(customer_groups[0]);
					}
				});
			}

			// Filter Supplier Group dropdown
			let sg_filter = qr.filters.find(function (f) {
				return f.df && f.df.fieldname === "supplier_group" &&
					f.df.fieldtype === "Link" &&
					f.df.options === "Supplier Group";
			});

			if (sg_filter) {
				get_permitted_supplier_groups(function (supplier_groups) {
					if (!supplier_groups || !supplier_groups.length) return;
					sg_filter.df.get_query = function () {
						return { filters: { name: ["in", supplier_groups] } };
					};
					if (supplier_groups.length === 1 && !sg_filter.get_value()) {
						sg_filter.set_value(supplier_groups[0]);
					}
				});
			}

			// Filter Sales Person dropdown
			let sp_filter = qr.filters.find(function (f) {
				return f.df && f.df.fieldname === "sales_person" &&
					f.df.fieldtype === "Link" &&
					f.df.options === "Sales Person";
			});

			if (sp_filter) {
				get_permitted_sales_persons(function (sales_persons) {
					if (!sales_persons || !sales_persons.length) return;
					sp_filter.df.get_query = function () {
						return { filters: { name: ["in", sales_persons] } };
					};
					if (sales_persons.length === 1 && !sp_filter.get_value()) {
						sp_filter.set_value(sales_persons[0]);
					}
				});
			}
		}, 500);
	}

	// ── 4. Block Export for restricted users on restricted doctypes ──

	function setup_export_block() {
		// Override DataExporter to block export before it even calls the server
		if (frappe.data_import && frappe.data_import.DataExporter) {
			let OrigExporter = frappe.data_import.DataExporter;
			frappe.data_import.DataExporter = function (doctype, exporting_for) {
				if (is_restricted_doctype(doctype)) {
					frappe.msgprint({
						title: __("Export Restricted"),
						message: __("You cannot export {0} data because you have restricted access. Contact your administrator.", [__(doctype)]),
						indicator: "red",
					});
					return { dialog: { show: function () {} } };
				}
				return new OrigExporter(doctype, exporting_for);
			};
		}

		// Also watch for page changes to hide Export from Actions menu
		$(document).on("page-change", block_export_on_page);
		setTimeout(block_export_on_page, 1000);
	}

	function is_restricted_doctype(doctype) {
		return RESTRICTED_CHILD_DOCTYPES.includes(doctype);
	}

	function block_export_on_page() {
		let route = frappe.get_route();
		if (!route || route.length < 2) return;

		// Detect doctype from List View or Report View route
		let view_type = route[0]; // "List" or "query-report" or slug
		let slug = view_type === "List" ? route[1] : route[0];
		let dt = null;
		RESTRICTED_CHILD_DOCTYPES.forEach(function (d) {
			if (frappe.router.slug(d) === slug || d === slug) {
				dt = d;
			}
		});
		// Also detect Report View: /app/quotation/view/report
		if (!dt && route.length >= 3 && route[2] === "report") {
			RESTRICTED_CHILD_DOCTYPES.forEach(function (d) {
				if (frappe.router.slug(d) === route[0] || d === route[0]) {
					dt = d;
				}
			});
		}
		if (!dt) return;

		// Patch Actions dropdown (appears when rows are checked)
		function patch_actions_menu() {
			let $menu = $(".actions-btn-group .dropdown-menu");
			if (!$menu.length) return;

			// Hide standard Export
			$menu.find("a").filter(function () {
				return $(this).text().trim() === "Export";
			}).closest("li").hide();

			// Add "Export My Data" if not already there
			if (!$menu.find("a:contains('Export My Data')").length) {
				let $li = $('<li><a class="dropdown-item" href="#">'
					+ __("Export My Data") + "</a></li>");
				$li.on("click", function (e) {
					e.preventDefault();
					show_my_data_export_dialog(dt);
				});
				$menu.append($li);
			}
		}

		// Patch ALL menus on the page — hide Export, add Export My Data
		function patch_page_menu() {
			// Target every dropdown-menu on the page (Menu "...", page actions, etc.)
			$(".dropdown-menu").each(function () {
				let $menu = $(this);
				// Skip the Actions dropdown (handled separately by patch_actions_menu)
				if ($menu.closest(".actions-btn-group").length) return;

				// Find and hide "Export" items
				let found_export = false;
				$menu.find("a, button, .dropdown-item").filter(function () {
					let txt = $(this).text().trim();
					return txt === "Export" || txt === __("Export");
				}).each(function () {
					found_export = true;
					$(this).closest("li").length
						? $(this).closest("li").hide()
						: $(this).hide();
				});

				// Add "Export My Data" if Export was found/hidden and our button isn't there
				if (found_export && !$menu.find(".export-my-data-btn").length) {
					let $item = $('<a class="dropdown-item export-my-data-btn" href="#">'
						+ __("Export My Data") + "</a>");
					$item.on("click", function (e) {
						e.preventDefault();
						show_my_data_export_dialog(dt);
					});
					$menu.append($item);
				}
			});
		}

		// Run immediately and on every DOM change
		let observer_started = false;
		let check_interval = setInterval(function () {
			let $actions_group = $(".actions-btn-group");
			let $page_container = $(".page-container, .frappe-control");

			patch_page_menu(); // Always patch the "..." menu

			if ($actions_group.length && !observer_started) {
				observer_started = true;
				patch_actions_menu();

				// Watch for Actions dropdown being rebuilt (on checkbox select/deselect)
				let observer = new MutationObserver(function () {
					setTimeout(function () {
						patch_actions_menu();
						patch_page_menu();
					}, 100);
				});
				observer.observe($actions_group[0], { childList: true, subtree: true });
			}

			// Also observe the page body for menu rebuilds
			if ($page_container.length && !$page_container.data("export-observer")) {
				$page_container.data("export-observer", true);
				let pageObserver = new MutationObserver(function () {
					setTimeout(patch_page_menu, 200);
				});
				pageObserver.observe($page_container[0], { childList: true, subtree: true });
				clearInterval(check_interval);
			}
		}, 500);
	}

	function show_my_data_export_dialog(doctype) {
		// Get selected records from list view
		let selected = [];
		try {
			if (typeof cur_list !== "undefined" && cur_list && cur_list.get_checked_items) {
				selected = cur_list.get_checked_items().map(function (item) {
					return item.name;
				});
			}
			if (!selected.length) {
				$(".list-row-checkbox:checked").each(function () {
					var name = $(this).data("name");
					if (name) selected.push(name);
				});
			}
		} catch (e) {
			// silently ignore
		}

		let d = new frappe.ui.Dialog({
			title: __("Export My Data — {0}", [__(doctype)]),
			fields: [
				{
					fieldname: "info",
					fieldtype: "HTML",
					options: '<p style="color:#888;">' +
						__("Export only the data you have permission to access.") +
						"</p>",
				},
				{
					fieldname: "export_scope",
					fieldtype: "Select",
					label: __("Export Scope"),
					options: __("All Permitted Records") + "\n" + __("Selected Records Only"),
					default: selected.length
						? __("Selected Records Only")
						: __("All Permitted Records"),
				},
				{
					fieldname: "docnames",
					fieldtype: "Small Text",
					label: __("Document Names (one per line)"),
					default: selected.join("\n"),
					depends_on: "eval:doc.export_scope=='" + __("Selected Records Only") + "'",
					description: __("Enter document names to export, one per line"),
				},
				{
					fieldname: "file_type",
					fieldtype: "Select",
					label: __("File Type"),
					options: "CSV\nExcel",
					default: "CSV",
				},
			],
			primary_action_label: __("Download"),
			primary_action: function () {
				let file_type = d.get_value("file_type");
				let scope = d.get_value("export_scope");
				let names_to_export = [];

				if (scope === __("Selected Records Only")) {
					let raw = d.get_value("docnames") || "";
					names_to_export = raw.split("\n")
						.map(function (n) { return n.trim(); })
						.filter(function (n) { return n; });
					if (!names_to_export.length) {
						frappe.msgprint(__("Please enter at least one document name."));
						return;
					}
				}

				d.hide();
				let url = "/api/method/avientek.api.quotation_access.export_my_data" +
					"?doctype=" + encodeURIComponent(doctype) +
					"&file_type=" + encodeURIComponent(file_type);
				if (names_to_export.length) {
					url += "&docnames=" + encodeURIComponent(JSON.stringify(names_to_export));
				}
				window.open(url);
			},
		});
		d.show();
	}

	// ── Initialize ──

	$(document).ready(function () {
		if (frappe.session.user === "Administrator") return;

		// Pre-warm restriction caches (used later by route intercept & report filters)
		check_brand_restriction(function () {});
		check_item_group_restriction(function () {});
		check_customer_group_restriction(function () {});
		check_supplier_group_restriction(function () {});
		check_sales_person_restriction(function () {});

		// Always set up for non-Admin users — server-side enforces real security,
		// client-side just provides UX (hide Export, show Export My Data, etc.)
		setup_route_intercept();
		setup_report_filters();
		setup_export_block();
	});

	// Global access for list view handlers
	window.show_brand_preview = show_restricted_preview;
})();
