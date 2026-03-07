// Copyright (c) 2026, Avientek and contributors
// For license information, please see license.txt

frappe.ui.form.on("Warranty List", {
	refresh(frm) {
		// Update days remaining on load
		if (frm.doc.warranty_end_date) {
			const days = frappe.datetime.get_diff(frm.doc.warranty_end_date, frappe.datetime.nowdate());
			frm.set_value("days_remaining", days);

			if (days < 0 && frm.doc.docstatus === 1 && frm.doc.status === "Under Warranty") {
				frm.call("run_doc_method", { method: "update_status_expired" });
			}
		}

		// Void button for active warranties
		if (frm.doc.docstatus === 1 && frm.doc.status === "Under Warranty") {
			frm.add_custom_button(__("Void Warranty"), () => {
				frappe.confirm(
					__("Are you sure you want to void this warranty?"),
					() => {
						frappe.xcall("frappe.client.set_value", {
							doctype: "Warranty List",
							name: frm.doc.name,
							fieldname: "status",
							value: "Voided",
						}).then(() => frm.reload_doc());
					}
				);
			});
		}

		// Create RMA Case from Warranty
		if (frm.doc.docstatus === 1 && frm.doc.status === "Under Warranty") {
			frm.add_custom_button(__("RMA Case"), () => {
				frappe.new_doc("RMA Case", {
					customer: frm.doc.customer,
					item_code: frm.doc.item_code,
					item_description: frm.doc.item_name,
					asset_serial_number: frm.doc.serial_no || "",
					warranty_list: frm.doc.name,
					warranty_status: "Under Warranty",
					warranty_expiry_date: frm.doc.warranty_end_date,
					company: frm.doc.company,
				});
			}, __("Create"));
		}
	},
});
