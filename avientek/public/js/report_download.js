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
	var POLL_INTERVAL_MS = 600;
	var BUTTON_TEXT = "Report Download";

	setInterval(ensure_button, POLL_INTERVAL_MS);

	function ensure_button() {
		var route = (typeof frappe !== "undefined" && frappe.get_route && frappe.get_route()) || [];
		if (!route || route.length < 3 || String(route[2]).toLowerCase() !== "report") return;
		if (typeof cur_list === "undefined" || !cur_list || !cur_list.page) return;
		if (typeof cur_list.page.add_button !== "function") return;

		// Dedupe by walking visible buttons near the page head. We use a
		// wide selector because Frappe's page action container differs a
		// little across versions (.page-actions / .standard-actions /
		// page-head .btn-group). If we find ANY button that renders the
		// exact text "Report Download" in the top area, skip — otherwise
		// the poller would stack a new button on every tick.
		var already = false;
		$('.page-head button, .page-actions button, .standard-actions button').each(function () {
			var txt = (this.textContent || "").trim();
			if (txt === BUTTON_TEXT) { already = true; return false; }
		});
		if (already) return;

		var $btn;
		try {
			$btn = cur_list.page.add_button(
				BUTTON_TEXT,
				function () { open_download_dialog(cur_list); },
				{ btn_class: "btn-default btn-sm", icon: "download" }
			);
		} catch (e) {
			// Frappe add_button occasionally throws before the page is ready;
			// the poller will retry on the next tick.
			return;
		}
		if ($btn && $btn.length) {
			$btn.attr("data-rpt-dl", "1");
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
			_rd_export_all(rv, dt, spec.headers, spec.keys, spec.parent_keys,
				spec.col_types, spec.col_options, values.file_type);
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
	// Sridhar 2026-05-10: track Frappe fieldtype + options per column so
	// the server writes Currency / Float / Int / Percent / Date as proper
	// Excel typed cells (with number_format) instead of strings. The
	// previous version sent everything as String(v) → Excel rendered
	// Grand Total / Net Rate / Amount as text, breaking sum/sort.
	var col_types = [];
	var col_options = [];

	cols.forEach(function (c) {
		var id = c.id || (c.df && c.df.fieldname) || c.name;
		if (!id) return;
		if (id === "_checkbox" || id === "_liked_by" || id === "name:no_display") return;

		var label = (c.df && c.df.label) || (c.docfield && c.docfield.label) || c.name || id;
		// Sammish 2026-05-16 (Jithin caught it on Quotation Item export):
		// For child-table columns Frappe's datatable puts the canonical
		// fieldtype on c.docfield (e.g. "Float" for qty), and c.df is
		// either missing or carries the datatable-internal "Data". Read
		// both so Currency / Float / Int / Percent on Quotation Item /
		// Sales Order Item etc. land as numeric cells in Excel.
		var ftype = (c.docfield && c.docfield.fieldtype)
			|| (c.df && c.df.fieldtype)
			|| "Data";
		var fopts = (c.docfield && c.docfield.options)
			|| (c.df && c.df.options)
			|| "";
		var child_dt = (c.docfield && c.docfield.parent) || null;
		var is_child = child_dt && child_dt !== dt;

		if (is_child && label && label.indexOf("(") === -1) {
			label = label + " (" + child_dt + ")";
		}

		headers.push(label);
		keys.push(id);
		col_types.push(ftype);
		col_options.push(fopts);
		if (!is_child) parent_keys.push(id);
	});

	if (!keys.length && (rv.data || []).length) {
		Object.keys(rv.data[0]).forEach(function (k) {
			if (!k || k === "_comment_count" || k === "docstatus" || k[0] === "_") return;
			headers.push(k.indexOf(":") >= 0 ? k : k);
			keys.push(k);
			col_types.push("Data");
			col_options.push("");
			if (k.indexOf(":") === -1) parent_keys.push(k);
		});
	}

	return {
		headers: headers,
		keys: keys,
		parent_keys: parent_keys,
		col_types: col_types,
		col_options: col_options,
	};
}


// Frappe fieldtypes that should be written as numeric cells.
var _RD_NUMERIC_TYPES = {
	"Currency": 1, "Float": 1, "Int": 1, "Percent": 1, "Long Int": 1,
};

function _rd_coerce_value(raw, ftype) {
	if (raw == null || raw === "") return "";
	if (_RD_NUMERIC_TYPES[ftype]) {
		if (typeof raw === "number") return raw;
		// Strip commas / spaces / leading currency symbols (د.إ, ر.س, $, etc.)
		var s = String(raw).replace(/[\s,]/g, "")
			.replace(/^[^\d\-+\.]+/, "")
			.replace(/[^\d\.\-eE]+$/, "");
		if (s === "" || s === "-") return "";
		var n = parseFloat(s);
		return isNaN(n) ? "" : n;
	}
	return String(raw);
}


/**
 * Export the Report View's data, respecting the user's row selection:
 *   - If rows are checked via the list-view checkboxes → export only
 *     those parent docs (and all their child rows).
 *   - Otherwise → bump page_length and refresh to fetch every row
 *     matching the current filters, then export.
 */
function _rd_export_all(rv, dt, headers, keys, parent_keys, col_types, col_options, file_type) {
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

		// Header row: always strings
		var rows = [headers];
		data.forEach(function (r) {
			rows.push(keys.map(function (k, i) {
				return _rd_coerce_value(r[k], (col_types || [])[i] || "Data");
			}));
		});

		if (file_type === "Excel") {
			open_url_post(
				"/api/method/avientek.api.quotation_access.export_report_as_excel",
				{
					data: JSON.stringify(rows),
					doctype: dt,
					col_types: JSON.stringify(col_types || []),
					col_options: JSON.stringify(col_options || []),
				}
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

	// Rahul 2026-06-02: previously hard-capped at 9999 rows per export.
	// Item / Item Price / Sales Order have 10k–160k rows on prod, so users
	// only ever got the first 9999. Switch to chunked pagination so we
	// accumulate ALL matching rows. Soft cap at 100,000 rows total per
	// export (browser memory + Excel practicality); warn if hit.
	//
	// Sridhar ERP-TKT-3 2026-06-05 (v1, e0782f5): used rv.refresh() and
	// read rv.data after each call. Hit a wall on Quotation report views
	// with child-table columns picked: Frappe base_list's `update_data`
	// applies `this.data.uniqBy((d) => d.name)` after every refresh.
	// Child-expanded responses collapse to one-row-per-parent in rv.data
	// even though the server returned thousands of expanded rows. My
	// growth-delta check saw added=0 and bailed. Rahul's Quotation export
	// landed at exactly 5000 rows because chunk 2's 10K-row server
	// response uniqBy'd back to the same 5K set chunk 1 returned.
	//
	// Sridhar ERP-TKT-3 2026-06-05 (v2): bypass rv.refresh() entirely
	// and call the server method directly via frappe.call with explicit
	// start + page_length per chunk. That skips uniqBy, the
	// page_length+=start mutation in before_refresh, and any other
	// list-view post-processing. We concat raw response rows into our
	// own buffer. Stop when a chunk returns < CHUNK rows (end of dataset)
	// or we hit MAX_ROWS.
	//
	// rv.method + rv.get_call_args() give us the exact method and args
	// the list view would use for its own refresh — same filters, same
	// fields, same group_by — so the export matches what the user sees.
	var CHUNK = 5000;
	var MAX_ROWS = 100000;
	var all_data = [];

	var base_call_args = (rv.get_call_args && rv.get_call_args()) || null;
	if (!base_call_args || !base_call_args.method) {
		frappe.msgprint(__("Cannot determine list view server endpoint — export aborted."));
		return;
	}

	function next_chunk() {
		var requested_start = all_data.length;
		var chunk_args_obj = Object.assign({}, base_call_args.args, {
			start: requested_start,
			page_length: CHUNK,
		});
		var call_args = {
			method: base_call_args.method,
			args: chunk_args_obj,
		};
		frappe.show_alert({
			message: __("Fetching rows {0}–{1} for export…",
				[requested_start + 1, requested_start + CHUNK]),
			indicator: "blue",
		}, 5);

		return frappe.call(call_args).then(function (r) {
			var msg = r && r.message;
			var rows = [];
			if (msg && msg.keys && msg.values) {
				// frappe.desk.reportview.get response shape — convert
				// the parallel keys/values arrays to row dicts.
				rows = frappe.utils.dict(msg.keys, msg.values);
			} else if (Array.isArray(msg)) {
				// frappe.client.get_list response shape — already an
				// array of dicts.
				rows = msg;
			}
			all_data = all_data.concat(rows);
			// End of dataset = server returned fewer than CHUNK rows
			// for this page. Safety cap as before.
			if (rows.length < CHUNK || all_data.length >= MAX_ROWS) {
				return;
			}
			return next_chunk();
		});
	}

	next_chunk().then(function () {
		if (all_data.length >= MAX_ROWS) {
			frappe.msgprint(__(
				"Export truncated at {0} rows. Apply narrower filters to export the remainder.",
				[MAX_ROWS]
			));
		}
		frappe.show_alert({
			message: __("Exporting {0} rows…", [all_data.length]),
			indicator: "green",
		}, 5);
		proceed(all_data);
	}).catch(function (err) {
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
