frappe.ui.form.on("Asset Capitalization", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.stock_items && frm.doc.stock_items.length) {
			frm.add_custom_button(__("Update Batch"), function () {
				_update_batch_dialog(frm);
			}, __("Tools"));
		}
	},
});

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
