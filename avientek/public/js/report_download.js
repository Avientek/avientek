/**
 * Report Download Button — loaded via doctype_list_js for each doctype.
 * One-click download of visible Report View columns and data as CSV.
 */

window.setTimeout(function() {
	var route = frappe.get_route();
	if (!route || route.length < 3 || route[2].toLowerCase() !== "report") return;
	if (!cur_list || !cur_list.page) return;
	if (cur_list._rpt_dl) return;
	cur_list._rpt_dl = true;

	cur_list.page.add_button(
		__("Report Download"),
		function() {
			if (!cur_list || !cur_list.report_view) {
				frappe.msgprint(__("Only available in Report View"));
				return;
			}
			var rv = cur_list.report_view;
			var dt = cur_list.doctype;
			var cols = rv.columns || [];
			if (!cols.length) { frappe.msgprint(__("No columns")); return; }
			var headers = [], fns = [];
			cols.forEach(function(c) {
				if (!c.df || !c.df.fieldname) return;
				headers.push(c.df.label || c.df.fieldname);
				fns.push(c.df.fieldname);
			});
			var data = rv.data || cur_list.data || [];
			if (!data.length) { frappe.msgprint(__("No data")); return; }
			var total = cur_list.total_count || data.length;
			if (total > data.length) {
				frappe.confirm(
					__("Showing {0} of {1}. Download all?", [data.length, total]),
					function() {
						var fields2 = [], headers2 = [];
						cols.forEach(function(c) {
							if (!c.df || !c.df.fieldname) return;
							var p = (c.docfield && c.docfield.parent) || dt;
							fields2.push("`tab" + p + "`.`" + c.df.fieldname + "`");
							headers2.push(c.df.label || c.df.fieldname);
						});
						frappe.call({
							method: "frappe.client.get_list",
							args: { doctype: dt, fields: fields2, filters: cur_list.get_filters_for_args(),
								order_by: cur_list.sort_by + " " + cur_list.sort_order, limit_page_length: 0 },
							freeze: true, freeze_message: __("Downloading..."),
							callback: function(r) {
								if (!r.message || !r.message.length) { frappe.msgprint(__("No data")); return; }
								var rows = [headers2];
								r.message.forEach(function(row) {
									rows.push(cols.map(function(c) {
										if (!c.df) return "";
										var v = row[c.df.fieldname]; return v == null ? "" : String(v);
									}));
								});
								window._rd_csv(rows, dt);
							}
						});
					},
					function() {
						var rows = [headers];
						data.forEach(function(r) {
							rows.push(fns.map(function(f) { var v = r[f]; return v == null ? "" : String(v); }));
						});
						window._rd_csv(rows, dt);
					}
				);
			} else {
				var rows = [headers];
				data.forEach(function(r) {
					rows.push(fns.map(function(f) { var v = r[f]; return v == null ? "" : String(v); }));
				});
				window._rd_csv(rows, dt);
			}
		},
		{ btn_class: "btn-primary-dark btn-sm", icon: "download" }
	);
}, 1000);

window._rd_csv = window._rd_csv || function(rows, dt) {
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
	a.download = (dt || "report") + "_" + frappe.datetime.now_date() + ".csv";
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
	frappe.show_alert({message: __("Downloaded {0} rows", [rows.length - 1]), indicator: "green"}, 3);
};
