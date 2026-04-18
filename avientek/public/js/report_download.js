/**
 * Report Download Button — loaded via doctype_list_js for each doctype.
 * One-click download of the CURRENT Report View columns and data as CSV/Excel.
 *
 * Runs generically across every doctype: whatever columns the user has picked
 * (parent fields, child-table fields, custom fields, linked-doctype fields)
 * are exported using the exact same data key Frappe's datatable uses
 * internally. So adding or removing columns via "Pick Columns" is always
 * reflected in the download with no doctype-specific code.
 */

(function () {
	var POLL_INTERVAL_MS = 600;   // how often we re-check the page
	var BUTTON_LABEL = __("Report Download");

	// Keep trying every POLL_INTERVAL_MS. The button is idempotent — it won't
	// double-add. This works across SPA navigation (List → Report → Dashboard →
	// back to Report) because we don't rely on a single onload event that fires
	// only once per page reload.
	setInterval(ensure_button, POLL_INTERVAL_MS);

	function ensure_button() {
		var route = (typeof frappe !== "undefined" && frappe.get_route && frappe.get_route()) || [];
		if (!route || route.length < 3 || String(route[2]).toLowerCase() !== "report") return;
		if (typeof cur_list === "undefined" || !cur_list || !cur_list.page) return;

		// If the button already exists in this page's toolbar, nothing to do.
		var $wrap = cur_list.page && cur_list.page.$wrapper;
		if ($wrap && $wrap.find('.btn-rpt-dl').length) return;

		var $btn = cur_list.page.add_button(
			BUTTON_LABEL,
			function () { open_download_dialog(cur_list); },
			{ btn_class: "btn-default btn-sm btn-rpt-dl", icon: "download" }
		);
		if ($btn && $btn.length) {
			$btn.addClass("btn-rpt-dl");
			$btn.css({ border: "1px solid #c0c6cc", "font-weight": "500" });
		}
	}
})();


function open_download_dialog(rv) {
	var dt = rv.doctype;
	var data = rv.data || [];
	if (!data.length) { frappe.msgprint(__("No data to download")); return; }

	var spec = _rd_build_column_spec(rv);
	if (!spec.keys.length) { frappe.msgprint(__("No columns to export")); return; }

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
		primary_action: function (values) {
			d.hide();
			_rd_export_all(rv, dt, spec.headers, spec.keys, spec.parent_keys, values.file_type);
		},
	});
	d.show();
}


/**
 * Figure out which column = which key in rv.data.
 *
 * IMPORTANT: Frappe's datatable uses the column's `id` as the row data key.
 * For parent-doctype fields id is just `fieldname`. For child-table fields
 * id is `fieldname:Child DocType` (fieldname first, then colon, then the
 * child doctype). An earlier version of this file built the key in the
 * REVERSE order (`Child DocType:fieldname`) which never matched — so
 * Sales Team columns and other child fields exported as blank.
 *
 * We now use `c.id` verbatim as the key and only use `c.df.fieldname` /
 * `c.docfield.parent` to (a) detect whether the column is from a child and
 * (b) pick a sensible human header label.
 */
function _rd_build_column_spec(rv) {
	var dt = rv.doctype;
	var cols = rv.columns || [];
	var headers = [];
	var keys = [];
	var parent_keys = [];

	cols.forEach(function (c) {
		var id = c.id || (c.df && c.df.fieldname) || c.name;
		if (!id) return;
		if (id === "_checkbox" || id === "_liked_by" || id === "name:no_display") return;

		var label = (c.df && c.df.label) || c.name || id;
		var child_dt = (c.docfield && c.docfield.parent) || null;
		var is_child = child_dt && child_dt !== dt;

		// Keep child-column labels distinguishable even if two tables share a
		// fieldname — e.g. "Sales Person (Sales Team)" rather than just
		// "Sales Person"
		if (is_child && label && label.indexOf("(") === -1) {
			label = label + " (" + child_dt + ")";
		}

		headers.push(label);
		keys.push(id);
		if (!is_child) parent_keys.push(id);
	});

	// Fallback: if we somehow didn't get columns metadata, use whatever keys
	// the first row carries. Parent keys are those without a colon.
	if (!keys.length && (rv.data || []).length) {
		Object.keys(rv.data[0]).forEach(function (k) {
			if (!k || k === "_comment_count" || k === "docstatus" || k[0] === "_") return;
			headers.push(k.indexOf(":") >= 0 ? k : k);
			keys.push(k);
			if (k.indexOf(":") === -1) parent_keys.push(k);
		});
	}

	return { headers: headers, keys: keys, parent_keys: parent_keys };
}


/**
 * Export the Report View's data, respecting the user's row selection:
 *   - If rows are checked via the list-view checkboxes → export only
 *     those parent docs (and all their child rows).
 *   - Otherwise → bump page_length and refresh to fetch every row
 *     matching the current filters, then export.
 */
function _rd_export_all(rv, dt, headers, keys, parent_keys, file_type) {
	var selected_names = [];
	try {
		var checked = (rv.get_checked_items && rv.get_checked_items()) || [];
		selected_names = checked.map(function (r) { return r && r.name; }).filter(Boolean);
	} catch (e) {
		selected_names = [];
	}

	var proceed = function (data) {
		if (!data || !data.length) {
			frappe.msgprint(__("No data to download"));
			return;
		}
		_rd_denormalize_parent_fields(data, parent_keys);

		var rows = [headers];
		data.forEach(function (r) {
			rows.push(keys.map(function (k) {
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
		var selected_set = {};
		selected_names.forEach(function (n) { selected_set[n] = true; });
		var data = (rv.data || []).filter(function (r) { return r && selected_set[r.name]; }).slice();
		frappe.show_alert({ message: __("Exporting {0} selected records…", [selected_names.length]), indicator: "blue" }, 5);
		proceed(data);
		return;
	}

	var prev_pl = rv.page_length;
	rv.page_length = 9999;

	frappe.show_alert({ message: __("Fetching all rows for export…"), indicator: "blue" }, 8);

	var refresh_result = rv.refresh();
	var p = (refresh_result && typeof refresh_result.then === "function")
		? refresh_result
		: new Promise(function (resolve) { setTimeout(resolve, 1500); });

	p.then(function () {
		rv.page_length = prev_pl;
		proceed((rv.data || []).slice());
	}).catch(function (err) {
		rv.page_length = prev_pl;
		frappe.msgprint(__("Failed to fetch all rows: {0}", [err || "unknown error"]));
	});
}


/**
 * Fill every child/item row with the parent's field values.
 * Frappe's Report View returns parent columns only on the first row of each
 * parent group; subsequent rows leave them blank. We walk in order, cache
 * each parent's first-seen non-blank values, and forward-fill.
 */
function _rd_denormalize_parent_fields(data, parent_keys) {
	if (!data || !data.length || !parent_keys || !parent_keys.length) return;
	var current_name = null;
	var parent_values_by_name = {};

	data.forEach(function (r) {
		var name = r["name"];
		if (name) {
			current_name = name;
			if (!parent_values_by_name[name]) {
				var cached = {};
				parent_keys.forEach(function (k) {
					if (r[k] != null && r[k] !== "") cached[k] = r[k];
				});
				parent_values_by_name[name] = cached;
			} else {
				parent_keys.forEach(function (k) {
					var cache = parent_values_by_name[name];
					if ((cache[k] == null || cache[k] === "") && r[k] != null && r[k] !== "") {
						cache[k] = r[k];
					}
				});
			}
		} else if (current_name) {
			r["name"] = current_name;
		}
		var pvals = parent_values_by_name[current_name] || {};
		parent_keys.forEach(function (k) {
			if ((r[k] == null || r[k] === "") && pvals[k] != null) {
				r[k] = pvals[k];
			}
		});
	});
}


function _rd_download_csv(rows, dt) {
	var csv = rows.map(function (r) {
		return r.map(function (c) {
			var s = String(c).replace(/"/g, '""');
			if (s.indexOf(",") >= 0 || s.indexOf("\n") >= 0 || s.indexOf('"') >= 0) s = '"' + s + '"';
			return s;
		}).join(",");
	}).join("\n");
	var blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
	var a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = dt + "_" + frappe.datetime.now_date() + ".csv";
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
	frappe.show_alert({ message: __("Downloaded {0} rows", [rows.length - 1]), indicator: "green" }, 3);
}
