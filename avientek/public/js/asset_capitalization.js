frappe.ui.form.on("Asset Capitalization", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.stock_items && frm.doc.stock_items.length) {
			frm.add_custom_button(__("Update Batch"), function () {
				_update_batch_dialog(frm);
			}, __("Tools"));
		}
		_render_stock_availability(frm);
	},
});

frappe.ui.form.on("Asset Capitalization Stock Item", {
	item_code(frm) { _render_stock_availability(frm); },
	warehouse(frm) { _render_stock_availability(frm); },
	stock_items_add(frm) { _render_stock_availability(frm); },
	stock_items_remove(frm) { _render_stock_availability(frm); },
});

function _render_stock_availability(frm) {
	const items = (frm.doc.stock_items || []).filter(r => r.item_code);
	const $wrapper = frm.fields_dict.stock_items.$wrapper;

	// Remove old panel if exists
	$wrapper.prev(".dam-stock-availability").remove();

	if (!items.length) return;

	// Collect unique item codes
	const item_codes = [...new Set(items.map(r => r.item_code))];

	frappe.call({
		method: "avientek.api.stock_availability.get_batch_stock",
		args: { item_codes: JSON.stringify(item_codes) },
		async: true,
		callback(r) {
			if (!r.message) return;
			const data = r.message;

			let html = `<div class="dam-stock-availability" style="
				background: var(--fg-color); border: 1px solid var(--border-color);
				border-radius: var(--border-radius-md); padding: 12px 15px;
				margin-bottom: 10px;">
				<div style="font-weight: 600; font-size: var(--text-md); margin-bottom: 8px;">
					${__("Available Stock")}
				</div>`;

			item_codes.forEach(item_code => {
				const stock = data[item_code] || [];
				html += `<div style="margin-bottom: 10px;">
					<div style="font-weight: 500; margin-bottom: 4px;">
						${frappe.utils.get_form_link("Item", item_code, true)} ${item_code}
					</div>`;

				if (!stock.length) {
					html += `<div class="text-muted" style="font-size: var(--text-sm); padding-left: 10px;">
						${__("No stock available")}
					</div>`;
				} else {
					html += `<table class="table table-bordered table-sm" style="
						font-size: var(--text-sm); margin-bottom: 0;">
						<thead><tr>
							<th>${__("Warehouse")}</th>
							<th>${__("Batch")}</th>
							<th style="text-align:right">${__("Available Qty")}</th>
						</tr></thead><tbody>`;

					stock.forEach(s => {
						const batch_display = s.batch_no
							? frappe.utils.get_form_link("Batch", s.batch_no, true)
							: `<span class="text-muted">${__("No Batch")}</span>`;
						const qty_color = s.qty > 0 ? "var(--text-on-green)" : "var(--text-on-red)";
						html += `<tr>
							<td>${s.warehouse}</td>
							<td>${batch_display}</td>
							<td style="text-align:right; font-weight:500;">${s.qty}</td>
						</tr>`;
					});

					html += `</tbody></table>`;
				}
				html += `</div>`;
			});

			html += `</div>`;

			// Insert above the stock_items table
			$wrapper.prev(".dam-stock-availability").remove();
			$(html).insertBefore($wrapper);
		},
	});
}

function _update_batch_dialog(frm) {
	const rows = (frm.doc.stock_items || []).filter(r => r.item_code);
	if (!rows.length) {
		frappe.msgprint(__("No stock items to update."));
		return;
	}

	const fields = [];
	rows.forEach((row, idx) => {
		if (idx > 0) {
			fields.push({ fieldtype: "Section Break" });
		}
		fields.push({
			fieldtype: "HTML",
			options: `<b>Row ${row.idx}: ${row.item_code}</b>
				<span class="text-muted"> — Warehouse: ${row.warehouse || "—"}, Qty: ${row.stock_qty || 1}</span>`,
		});
		fields.push({
			fieldname: `batch_${row.idx}`,
			fieldtype: "Link",
			label: __("Batch No"),
			options: "Batch",
			default: row.batch_no || "",
			get_query: () => ({
				filters: { item: row.item_code },
			}),
		});
		fields.push({
			fieldname: `serial_${row.idx}`,
			fieldtype: "Small Text",
			label: __("Serial No"),
			default: row.serial_no || "",
		});
	});

	const d = new frappe.ui.Dialog({
		title: __("Update Batch / Serial No"),
		fields: fields,
		primary_action_label: __("Update"),
		primary_action(values) {
			rows.forEach(row => {
				const batch = values[`batch_${row.idx}`];
				const serial = values[`serial_${row.idx}`];
				if (batch !== undefined) {
					frappe.model.set_value(row.doctype, row.name, "batch_no", batch || "");
					frappe.model.set_value(row.doctype, row.name, "use_serial_batch_fields", batch || serial ? 1 : 0);
				}
				if (serial !== undefined) {
					frappe.model.set_value(row.doctype, row.name, "serial_no", serial || "");
					frappe.model.set_value(row.doctype, row.name, "use_serial_batch_fields", batch || serial ? 1 : 0);
				}
			});
			d.hide();
			frm.dirty();
			frappe.show_alert({ message: __("Batch / Serial No updated"), indicator: "green" });
		},
	});
	d.show();
}
