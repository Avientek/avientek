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

			// Build columns from the datatable's visible columns
			// The datatable header has the labels, data keys match column IDs
			var cols = rv.columns || [];
			var headers = [];
			var keys = [];

			if (cols.length) {
				cols.forEach(function(c) {
					var id = c.id || (c.df && c.df.fieldname) || "";
					if (!id || id === "_checkbox" || id === "_liked_by" || id === "name:no_display") return;
					var label = (c.df && c.df.label) || c.name || id;
					// Data key: for child fields it's "Child DocType:fieldname"
					// For parent fields it's just "fieldname"
					var key = (c.docfield && c.docfield.parent && c.docfield.parent !== dt)
						? c.docfield.parent + ":" + (c.df ? c.df.fieldname : id)
						: (c.df ? c.df.fieldname : id);
					headers.push(label);
					keys.push(key);
				});
			}

			// Fallback: if no columns extracted, use data keys directly
			if (!keys.length && data.length > 0) {
				Object.keys(data[0]).forEach(function(k) {
					if (k === "_comment_count" || k === "docstatus") return;
					headers.push(k.replace(/.*:/, "")); // "Quotation Item:item_code" → "item_code"
					keys.push(k);
				});
			}

			if (!keys.length) { frappe.msgprint(__("No columns to export")); return; }

			// Ask file type
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

					var rows = [headers];
					data.forEach(function(r) {
						rows.push(keys.map(function(k) {
							var v = r[k];
							return v == null ? "" : String(v);
						}));
					});

					if (values.file_type === "Excel") {
						open_url_post(
							"/api/method/avientek.api.quotation_access.export_report_as_excel",
							{ data: JSON.stringify(rows), doctype: dt }
						);
					} else {
						_rd_download_csv(rows, dt);
					}
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
