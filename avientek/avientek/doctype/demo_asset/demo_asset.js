frappe.ui.form.on("Demo Asset", {
	refresh(frm) {
		frm.trigger("set_status_indicator");
		frm.trigger("add_action_buttons");
	},

	asset(frm) {
		if (frm.doc.asset) {
			// Auto-fill company from asset (serial number entered manually — not a direct Asset field)
			frappe.db.get_value("Asset", frm.doc.asset, ["company", "asset_name"], (r) => {
				if (r) {
					frm.set_value("company", r.company);
				}
			});
		}
	},

	set_status_indicator(frm) {
		const color_map = {
			"Free": "green",
			"On Demo": "orange",
			"Issued as Standby": "blue",
			"In Repair": "yellow",
			"Written Off": "red",
			"Sold": "gray",
		};
		const color = color_map[frm.doc.status] || "gray";
		frm.page.set_indicator(frm.doc.status, color);
	},

	add_action_buttons(frm) {
		if (frm.is_new()) return;

		// Move Out for Demo
		if (frm.doc.status === "Free") {
			frm.add_custom_button(__("Move Out for Demo"), () => {
				frappe.new_doc("Demo Movement", {
					demo_asset: frm.doc.name,
					movement_type: "Move Out",
					company: frm.doc.company,
					serial_number: frm.doc.serial_number,
				});
			}, __("Actions"));
		}

		// Record Return
		if (frm.doc.status === "On Demo" || frm.doc.status === "Issued as Standby") {
			frm.add_custom_button(__("Record Return"), () => {
				frappe.new_doc("Demo Movement", {
					demo_asset: frm.doc.name,
					movement_type: "Return",
					company: frm.doc.company,
					serial_number: frm.doc.serial_number,
				});
			}, __("Actions"));
		}

		// View Movements
		frm.add_custom_button(__("Movement History"), () => {
			frappe.set_route("List", "Demo Movement", {
				demo_asset: frm.doc.name,
			});
		}, __("View"));
	},
});
