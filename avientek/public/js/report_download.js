/**
 * Report Download Button — loaded via doctype_list_js for each doctype.
 * One-click download of visible Report View columns and data as CSV/Excel.
 */

window.setTimeout(function() {
	var route = frappe.get_route();
	if (!route || route.length < 3 || route[2].toLowerCase() !== "report") return;
	if (!cur_list || !cur_list.page) return;
	if (cur_list._rpt_dl) return;
	cur_list._rpt_dl = true;

	var $btn = cur_list.page.add_button(
		__("Report Download"),
		function() {
			var rv = cur_list;
			var dt = rv.doctype;
			var data = rv.data || [];
			if (!data.length) { frappe.msgprint(__("No data to download")); return; }

			// Build columns from the datatable's visible columns.
			// The datatable header has the labels, data keys match column IDs.
			// Track which keys belong to the PARENT doctype vs a child table so
			// we can denormalize parent fields across every child row later.
			var cols = rv.columns || [];
			var headers = [];
			var keys = [];
			var parent_keys = [];  // keys that come from the parent doctype

			if (cols.length) {
				cols.forEach(function(c) {
					var id = c.id || (c.df && c.df.fieldname) || "";
					if (!id || id === "_checkbox" || id === "_liked_by" || id === "name:no_display") return;
					var label = (c.df && c.df.label) || c.name || id;
					var is_child_field = (c.docfield && c.docfield.parent && c.docfield.parent !== dt);
					// Data key: for child fields it's "Child DocType:fieldname"
					// For parent fields it's just "fieldname"
					var key = is_child_field
						? c.docfield.parent + ":" + (c.df ? c.df.fieldname : id)
						: (c.df ? c.df.fieldname : id);
					headers.push(label);
					keys.push(key);
					if (!is_child_field) parent_keys.push(key);
				});
			}

			// Fallback: if no columns extracted, use data keys directly
			if (!keys.length && data.length > 0) {
				Object.keys(data[0]).forEach(function(k) {
					if (k === "_comment_count" || k === "docstatus") return;
					headers.push(k.replace(/.*:/, "")); // "Quotation Item:item_code" → "item_code"
					keys.push(k);
					// Keys without ":" are parent fields (ERPNext's RV convention)
					if (k.indexOf(":") === -1) parent_keys.push(k);
				});
			}

			if (!keys.length) { frappe.msgprint(__("No columns to export")); return; }

			// Ask file type — the heavy "fetch all rows" only runs after the
			// user commits to downloading (so Cancel is cheap).
			var d = new frappe.ui.Dialog({
				title: __("Report Download"),
				fields: [{
					fieldname: "file_type",
					fieldtype: "Select",
					label: __("File Type"),
					options: "Excel\nCSV",
					default: "Excel",
				}],
				primary_action_label: __("Download"),
				primary_action: function(values) {
					d.hide();
					_rd_export_all(rv, dt, headers, keys, parent_keys, values.file_type);
				}
			});
			d.show();
		},
		{ btn_class: "btn-default btn-sm", icon: "download" }
	);
	if ($btn && $btn.length) {
		$btn.css({"border": "1px solid #c0c6cc", "font-weight": "500"});
	}
}, 1000);

/**
 * Export the Report View's data, respecting the user's row selection:
 *   - If rows are checked via the list-view checkboxes → export only
 *     those parent docs (and all their child rows).
 *   - Otherwise → bump page_length and refresh to fetch every row
 *     matching the current filters, then export.
 *
 * Fixes two complaints:
 *   - "I selected 20 but downloaded 41" (selection was ignored)
 *   - "reports is not pulling the full data" (export was capped at the
 *     visible page_length of ~20 when no selection was made)
 */
function _rd_export_all(rv, dt, headers, keys, parent_keys, file_type) {
	// Collect selected parent-doc names (if any).
	var selected_names = [];
	try {
		var checked = (rv.get_checked_items && rv.get_checked_items()) || [];
		selected_names = checked
			.map(function(r) { return r && r.name; })
			.filter(Boolean);
	} catch (e) {
		selected_names = [];
	}

	var proceed = function(data) {
		if (!data || !data.length) {
			frappe.msgprint(__("No data to download"));
			return;
		}
		_rd_denormalize_parent_fields(data, parent_keys);

		var rows = [headers];
		data.forEach(function(r) {
			rows.push(keys.map(function(k) {
				var v = r[k];
				return v == null ? "" : String(v);
			}));
		});

		if (file_type === "Excel") {
			open_url_post(
				"/api/method/avientek.api.quotation_access.export_report_as_excel",
				{ data: JSON.stringify(rows), doctype: dt }
			);
		} else {
			_rd_download_csv(rows, dt);
		}
	};

	if (selected_names.length) {
		// Checkbox selection wins — export exactly those parents, nothing
		// more. rv.data already has their rows (user ticked them from the
		// visible list), so we filter client-side; no extra round-trip.
		var selected_set = {};
		selected_names.forEach(function(n) { selected_set[n] = true; });
		var data = (rv.data || []).filter(function(r) {
			return r && selected_set[r.name];
		}).slice();
		frappe.show_alert({
			message: __("Exporting {0} selected records…", [selected_names.length]),
			indicator: "blue",
		}, 5);
		proceed(data);
		return;
	}

	// No selection — fetch every row matching the current filters.
	var prev_pl = rv.page_length;
	rv.page_length = 9999;

	frappe.show_alert({
		message: __("Fetching all rows for export…"),
		indicator: "blue",
	}, 8);

	var refresh_result = rv.refresh();
	var p = (refresh_result && typeof refresh_result.then === "function")
		? refresh_result
		: new Promise(function(resolve) { setTimeout(resolve, 1500); });

	p.then(function() {
		rv.page_length = prev_pl;
		proceed((rv.data || []).slice());
	}).catch(function(err) {
		rv.page_length = prev_pl;
		frappe.msgprint(__("Failed to fetch all rows: {0}", [err || "unknown error"]));
	});
}


/**
 * Fill every child/item row with the parent's field values.
 *
 * Frappe's Report View groups rows by parent and returns parent fields
 * only on the first row of each group. We walk the data in order, and
 * whenever a row has a non-empty `name`, we remember it as the current
 * parent and cache that row's parent-field values. Subsequent rows with
 * a blank `name` inherit the current parent's name AND any blank
 * parent-field values. First-seen non-blank values win, so parent field
 * changes within a group don't clobber the original.
 */
function _rd_denormalize_parent_fields(data, parent_keys) {
	if (!data || !data.length || !parent_keys || !parent_keys.length) return;
	var current_name = null;
	var parent_values_by_name = {};

	data.forEach(function(r) {
		var name = r["name"];
		if (name) {
			current_name = name;
			if (!parent_values_by_name[name]) {
				var cached = {};
				parent_keys.forEach(function(k) {
					if (r[k] != null && r[k] !== "") cached[k] = r[k];
				});
				parent_values_by_name[name] = cached;
			} else {
				// Top up any parent key we hadn't seen yet for this parent
				parent_keys.forEach(function(k) {
					if ((parent_values_by_name[name][k] == null || parent_values_by_name[name][k] === "") &&
						r[k] != null && r[k] !== "") {
						parent_values_by_name[name][k] = r[k];
					}
				});
			}
		} else if (current_name) {
			r["name"] = current_name;
		}
		var pvals = parent_values_by_name[current_name] || {};
		parent_keys.forEach(function(k) {
			if ((r[k] == null || r[k] === "") && pvals[k] != null) {
				r[k] = pvals[k];
			}
		});
	});
}


function _rd_download_csv(rows, dt) {
	var csv = rows.map(function(r) {
		return r.map(function(c) {
			var s = String(c).replace(/"/g, '""');
			if (s.indexOf(",") >= 0 || s.indexOf("\n") >= 0 || s.indexOf('"') >= 0) s = '"' + s + '"';
			return s;
		}).join(",");
	}).join("\n");
	var blob = new Blob(["\uFEFF" + csv], {type: "text/csv;charset=utf-8;"});
	var a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = dt + "_" + frappe.datetime.now_date() + ".csv";
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
	frappe.show_alert({message: __("Downloaded {0} rows", [rows.length - 1]), indicator: "green"}, 3);
}
