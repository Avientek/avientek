frappe.ui.form.on("Asset Capitalization", {
	refresh(frm) {
		_render_stock_availability(frm);
		_render_individual_assets(frm);
		_add_update_batch_btn(frm);
		_add_recreate_asset_btn(frm);

		// Override target_item_code filter: only items with "Is Asset Capitalization" checked
		frm.set_query("target_item_code", () => {
			return erpnext.queries.item({
				is_stock_item: 0,
				is_fixed_asset: 1,
				custom_is_asset_capitalization: 1,
			});
		});

		// Create Purchase Order button on draft forms with stock items
		if (frm.doc.docstatus === 0 && (frm.doc.stock_items || []).filter(r => r.item_code).length) {
			frm.add_custom_button(__("Purchase Order"), () => {
				_create_purchase_order(frm);
			}, __("Create"));
		}
	},
});

function _render_individual_assets(frm) {
	const $wrapper = frm.fields_dict.stock_items.$wrapper;
	$wrapper.prev(".dam-individual-assets").remove();

	if (frm.doc.docstatus !== 1) return;
	const assets_str = frm.doc.custom_individual_assets || "";
	if (!assets_str) return;

	const asset_names = assets_str.split(",").map(a => a.trim()).filter(Boolean);
	if (!asset_names.length) return;

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Asset",
			filters: { name: ["in", asset_names] },
			fields: ["name", "asset_name", "status", "gross_purchase_amount", "custom_part_no", "docstatus"],
			limit_page_length: 0,
		},
		async: true,
		callback(r) {
			if (!r.message || !r.message.length) return;
			$wrapper.prev(".dam-individual-assets").remove();

			const assets = r.message;
			let html = `<div class="dam-individual-assets" style="
				background: var(--fg-color); border: 1px solid var(--border-color);
				border-radius: var(--border-radius-md); padding: 12px 15px;
				margin-bottom: 10px;">
				<div style="font-weight: 600; font-size: var(--text-md); margin-bottom: 8px;">
					${__("Individual Assets Created")} (${assets.length})
				</div>
				<table class="table table-bordered table-sm" style="
					font-size: var(--text-sm); margin-bottom: 0;">
					<thead><tr>
						<th>${__("Asset")}</th>
						<th>${__("Asset Name")}</th>
						<th>${__("Part No")}</th>
						<th style="text-align:right">${__("Value")}</th>
						<th>${__("Status")}</th>
					</tr></thead><tbody>`;

			assets.forEach(a => {
				const status_color = a.docstatus === 2 ? "red"
					: (a.status === "Submitted" || a.status === "Free") ? "green" : "orange";
				const status_label = a.docstatus === 2 ? __("Cancelled") : __(a.status || "Draft");
				html += `<tr>
					<td>${frappe.utils.get_form_link("Asset", a.name, true)}</td>
					<td>${a.asset_name || ""}</td>
					<td>${a.custom_part_no || ""}</td>
					<td style="text-align:right">${format_currency(a.gross_purchase_amount)}</td>
					<td><span class="indicator-pill ${status_color}">${status_label}</span></td>
				</tr>`;
			});

			html += `</tbody></table></div>`;
			$(html).insertBefore($wrapper);
		},
	});
}

function _add_update_batch_btn(frm) {
	if (frm.doc.docstatus !== 0) return;
	const grid = frm.fields_dict.stock_items.grid;
	const $btnRow = grid.wrapper.find(".grid-footer .btn-open-row").parent();

	// Remove old button if exists
	$btnRow.find(".btn-update-batch").remove();

	if (!(frm.doc.stock_items || []).length) return;

	const $btn = $(`<button class="btn btn-xs btn-default btn-update-batch" style="margin-left: 8px;">
		${__("Update Batch")}
	</button>`);
	$btn.on("click", () => _update_batch_dialog(frm));
	$btnRow.append($btn);
}

frappe.ui.form.on("Asset Capitalization Stock Item", {
	item_code(frm, cdt, cdn) {
		_render_stock_availability(frm);
		_auto_select_fifo_batch(frm, cdt, cdn);
	},
	warehouse(frm, cdt, cdn) {
		_render_stock_availability(frm);
		_auto_select_fifo_batch(frm, cdt, cdn);
	},
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
		args: { item_codes: JSON.stringify(item_codes), company: frm.doc.company || "" },
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
						${frappe.utils.get_form_link("Item", item_code, true)}
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

function _add_recreate_asset_btn(frm) {
	if (frm.doc.docstatus !== 1) return;
	const assets_str = frm.doc.custom_individual_assets || "";
	if (!assets_str) return;

	// Check if any individual asset is cancelled
	const asset_names = assets_str.split(",").map(a => a.trim()).filter(Boolean);
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Asset",
			filters: { name: ["in", asset_names], docstatus: 2 },
			fields: ["name"],
			limit_page_length: 0,
		},
		async: true,
		callback(r) {
			if (r.message && r.message.length) {
				frm.add_custom_button(
					__("Recreate Cancelled Assets ({0})", [r.message.length]),
					() => {
						frappe.confirm(
							__("Recreate {0} cancelled asset(s)?", [r.message.length]),
							() => {
								frappe.call({
									method: "avientek.events.asset_capitalization.recreate_cancelled_assets",
									args: { docname: frm.doc.name },
									freeze: true,
									freeze_message: __("Creating assets..."),
									callback() { frm.reload_doc(); },
								});
							}
						);
					},
					__("Actions")
				);
			}
		},
	});
}

function _create_purchase_order(frm) {
	const rows = (frm.doc.stock_items || []).filter(r => r.item_code);
	if (!rows.length) {
		frappe.msgprint(__("No stock items to order."));
		return;
	}

	const items = rows.map(row => ({
		item_code: row.item_code,
		qty: row.stock_qty || 1,
		warehouse: row.warehouse || "",
		uom: row.stock_uom || "",
	}));

	frappe.new_doc("Purchase Order", {
		company: frm.doc.company,
		items: items,
	});
}

function _auto_select_fifo_batch(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	if (!row.item_code || !row.warehouse) return;

	// Check if item has batch tracking
	frappe.db.get_value("Item", row.item_code, "has_batch_no", (r) => {
		if (!r || !r.has_batch_no) return;

		frappe.call({
			method: "avientek.api.stock_availability.get_fifo_batch",
			args: {
				item_code: row.item_code,
				warehouse: row.warehouse,
				company: frm.doc.company || "",
			},
			callback(resp) {
				if (resp.message && resp.message.batch_no) {
					frappe.model.set_value(cdt, cdn, "batch_no", resp.message.batch_no);
					frappe.model.set_value(cdt, cdn, "use_serial_batch_fields", 1);
				}
			},
		});
	});
}
