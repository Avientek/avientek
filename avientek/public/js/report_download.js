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

		// Sridhar/Rahul 2026-06-10: previous guard was
		//   label.indexOf("(") === -1
		// which false-fired on labels that legitimately contain a "(",
		// like "Margin (%)" / "Discount (%)" / "Rate (Q...". Result: in
		// the downloaded xlsx, both Margin (%) columns (Quotation Item +
		// Optional Item) showed up as plain "Margin (%)" with no
		// child-table disambiguation — and the user couldn't tell them
		// apart. Check for the SPECIFIC " (child_dt)" suffix instead so
		// percent / rate labels still get disambiguated.
		if (is_child && label) {
			var disambig = " (" + child_dt + ")";
			if (label.indexOf(disambig) === -1) {
				label = label + disambig;
			}
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
 * Extract a human-readable error message from whatever frappe.call
 * rejects with. The rejection shape varies — sometimes a string,
 * sometimes a jqXHR-like object with responseJSON / responseText,
 * sometimes a Frappe error response with _server_messages /
 * exception. Without this helper, the error reaches the UI as
 * "[object Object]" — Sridhar reported exactly this on chunk 85
 * of a Sales Order export on avientekv21.frappe.cloud.
 */
function _rd_format_error(err) {
	if (!err) return "unknown error";
	if (typeof err === "string") return err;
	// Frappe-style: _server_messages is a JSON string of JSON strings
	if (err._server_messages) {
		try {
			var msgs = JSON.parse(err._server_messages);
			if (Array.isArray(msgs) && msgs.length) {
				return msgs.map(function (m) {
					try { return JSON.parse(m).message || m; } catch (e) { return m; }
				}).join("; ");
			}
		} catch (e) { /* fall through */ }
	}
	if (err.exception) return String(err.exception);
	if (err.responseJSON && err.responseJSON.exception) {
		return String(err.responseJSON.exception);
	}
	if (err.responseText) return String(err.responseText).slice(0, 200);
	if (err.statusText) {
		return err.statusText + (err.status ? " (HTTP " + err.status + ")" : "");
	}
	if (err.message) return String(err.message);
	try { return JSON.stringify(err).slice(0, 200); } catch (e) { return String(err); }
}


/**
 * Wrap frappe.call with exponential-backoff retry. Used by the
 * chunked Excel export so a transient 500 / network blip on a single
 * chunk doesn't abort the entire upload — common for long exports
 * (Sridhar's 42K-row Sales Order export failed on chunk 85 of ~85,
 * almost certainly transient since chunks 1-84 succeeded).
 *
 * Up to MAX_ATTEMPTS tries. Backoff: attempt 1 immediate, attempt 2
 * after 2s, attempt 3 after 4s. Total worst-case wait per chunk = 6s.
 */
function _rd_call_with_retry(call_args, max_attempts) {
	max_attempts = max_attempts || 3;
	var attempt = 0;
	function try_once() {
		attempt++;
		return frappe.call(call_args).catch(function (err) {
			if (attempt < max_attempts) {
				var backoff_ms = attempt * 2000;
				if (window.console && console.warn) {
					console.warn("[Avientek Export] attempt " + attempt + " failed: "
						+ _rd_format_error(err) + " — retrying in " + backoff_ms + "ms");
				}
				return new Promise(function (resolve) {
					setTimeout(resolve, backoff_ms);
				}).then(try_once);
			}
			// Re-throw the LAST error so the caller's .catch sees it.
			throw err;
		});
	}
	return try_once();
}


/**
 * POST the assembled rows (header + data rows, each row is an array of
 * cell values) to the server in chunks of 500. Server accumulates them
 * in cache keyed by session_token; the final chunk triggers workbook
 * build + returns the file as base64. Client decodes + downloads ONE
 * .xlsx file.
 *
 * Sridhar 2026-06-05 (v3): avoids the 413 Request Entity Too Large error
 * on Frappe Cloud nginx for exports > ~2K rows (default
 * client_max_body_size ≈ 1MB; a 6800-row Quotation export was ~3-5MB
 * in a single POST). Chunks of 500 keep each request well under any
 * reasonable body limit.
 *
 * Sridhar 2026-06-05 (v4): added retry-with-backoff per chunk +
 * better error messages. A 42K-row Sales Order export on
 * avientekv21.frappe.cloud failed on chunk 85 of 85 with "[object
 * Object]" — caused by my old catch handler stringifying the
 * rejection object naively. Now each chunk gets up to 3 attempts
 * (immediate, +2s, +4s) before bailing, and failures show the real
 * error text. Almost all real-world chunk failures are transient
 * (rate limit / brief Redis spike / network blip) so retry recovers
 * silently.
 */
function _rd_chunked_excel_post(rows, doctype, col_types, col_options) {
	var BATCH = 500;
	var session_token = String(Date.now()) + "_" + Math.random().toString(36).slice(2, 10);
	var total_chunks = Math.max(1, Math.ceil(rows.length / BATCH));

	function send(i) {
		var start = i * BATCH;
		var end = start + BATCH;
		var batch = rows.slice(start, end);
		var is_last = (i === total_chunks - 1);

		// Sridhar/Rahul 2026-06-10: silent uploads — was firing one
		// "Uploading rows X–Y of Z…" toast per chunk, which for a 27K-row
		// export meant 55+ toasts spamming the corner of the screen.
		// The "Downloaded N rows" toast at the end (and the earlier
		// "Exporting N rows…" once-only after fetch completes) carry
		// enough signal. The user sees the work happening via the
		// browser tab spinner and the fetch-step toast; the final
		// success toast confirms completion.

		var call_args = {
			method: "avientek.api.quotation_access.export_report_as_excel_chunked",
			args: {
				session_token: session_token,
				chunk_index: i,
				total_chunks: total_chunks,
				data: JSON.stringify(batch),
				doctype: doctype,
				// Only the final chunk needs the metadata — but we send it
				// every time so the server build code stays simple. Cheap.
				col_types: JSON.stringify(col_types || []),
				col_options: JSON.stringify(col_options || []),
			},
			type: "POST",
		};

		return _rd_call_with_retry(call_args, 3).then(function (r) {
			var msg = r && r.message;
			if (is_last) {
				if (msg && msg.complete && msg.filecontent_base64) {
					_rd_trigger_download_base64(
						msg.filecontent_base64,
						msg.filename || (doctype + ".xlsx"),
						"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
					);
					frappe.show_alert({
						message: __("Downloaded {0} rows", [rows.length - 1]),
						indicator: "green",
					}, 5);
				} else {
					frappe.msgprint(__("Export failed — server did not return the file"));
				}
			} else {
				return send(i + 1);
			}
		}).catch(function (err) {
			var reason = _rd_format_error(err);
			frappe.msgprint({
				title: __("Export Failed"),
				message: __(
					"Chunk {0} of {1} failed after 3 retries.<br><br>"
					+ "<b>Server says:</b> {2}<br><br>"
					+ "<i>Cause is usually a transient Frappe Cloud rate-limit or "
					+ "session expiry on very long exports. Try clicking "
					+ "Report Download again — it will start a fresh session.</i>",
					[i + 1, total_chunks, reason]
				),
				indicator: "red",
			});
		});
	}
	return send(0);
}


/**
 * Decode a base64 string into a Blob and trigger a browser download.
 * Used by `_rd_chunked_excel_post` to deliver the final .xlsx file.
 */
function _rd_trigger_download_base64(b64, filename, mime) {
	var byteChars = atob(b64);
	var len = byteChars.length;
	var byteArray = new Uint8Array(len);
	for (var i = 0; i < len; i++) {
		byteArray[i] = byteChars.charCodeAt(i);
	}
	var blob = new Blob([byteArray], { type: mime || "application/octet-stream" });
	var url = URL.createObjectURL(blob);
	var a = document.createElement("a");
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
	// Free the blob URL after the download starts
	setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
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
			// Sridhar 2026-06-05: Frappe Cloud nginx rejected single-POST
			// exports > ~2K rows with 413 Request Entity Too Large.
			// Send the rows to `export_report_as_excel_chunked` in
			// batches of 500 — server accumulates in Redis cache keyed
			// by session_token, builds the workbook on the final chunk,
			// returns the file as base64 in JSON. Client decodes to
			// Blob and triggers ONE download — the chunking is
			// invisible to the user.
			_rd_chunked_excel_post(rows, dt, col_types, col_options);
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
		// Sridhar/Rahul 2026-06-10: silent fetch — was firing one
		// "Fetching rows X–Y for export…" toast per chunk, which on a
		// 27K-row export stacked 50+ alerts in the corner of the screen.
		// The post-fetch "Exporting N rows…" toast (once) and the final
		// "Downloaded N rows" toast (once) carry enough signal.

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
