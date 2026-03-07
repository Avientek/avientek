// Copyright (c) 2026, Avientek and contributors
// For license information, please see license.txt

frappe.ui.form.on("Demo Unit Request", {

	refresh(frm) {
		frm.set_query("item_code", () => ({
			filters: { is_stock_item: 1 },
		}));

		frm.set_query("warehouse", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));

		_render_available_demo_assets(frm);
		_render_stock_availability(frm);

		// On submitted forms
		if (frm.doc.docstatus === 1) {
			// Status action buttons (only when Approved/Pending)
			if (frm.doc.status === "Approved" || frm.doc.status === "Pending") {
				frm.add_custom_button(__("Fulfilled"), () => {
					frappe.call({
						method: "set_fulfilled",
						doc: frm.doc,
						callback() { frm.reload_doc(); },
					});
				}, __("Status"));

				frm.add_custom_button(__("Rejected"), () => {
					frappe.call({
						method: "set_rejected",
						doc: frm.doc,
						callback() { frm.reload_doc(); },
					});
				}, __("Status"));
			}

			// Create buttons (only when not Fulfilled/Rejected/Cancelled)
			if (!["Fulfilled", "Rejected", "Cancelled"].includes(frm.doc.status)) {
				frm.add_custom_button(__("Asset Capitalization"), () => {
					frappe.new_doc("Asset Capitalization", {
						company: frm.doc.company,
						custom_demo_unit_request: frm.doc.name,
						stock_items: [{
							item_code: frm.doc.item_code,
							stock_qty: frm.doc.qty || 1,
							warehouse: frm.doc.warehouse || "",
						}],
					});
				}, __("Create"));

				frm.add_custom_button(__("Purchase Order"), () => {
					frappe.new_doc("Purchase Order", {
						company: frm.doc.company,
						custom_demo_unit_request: frm.doc.name,
						items: [{
							item_code: frm.doc.item_code,
							qty: frm.doc.qty || 1,
							warehouse: frm.doc.warehouse || "",
						}],
					});
				}, __("Create"));
			}
		}
	},

	item_code(frm) {
		_render_available_demo_assets(frm);
		_render_stock_availability(frm);
	},

	company(frm) {
		_render_available_demo_assets(frm);
		_render_stock_availability(frm);
	},
});

function _render_stock_availability(frm) {
	const $wrapper = frm.fields_dict.stock_availability_html.$wrapper;
	$wrapper.html("");

	if (!frm.doc.item_code) return;

	const item_codes = [frm.doc.item_code];

	frappe.call({
		method: "avientek.api.stock_availability.get_batch_stock",
		args: { item_codes: JSON.stringify(item_codes), company: frm.doc.company || "" },
		async: true,
		callback(r) {
			if (!r.message) return;
			const data = r.message;

			let html = `<div style="
				background: var(--fg-color); border: 1px solid var(--border-color);
				border-radius: var(--border-radius-md); padding: 12px 15px;">
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
			$wrapper.html(html);
		},
	});
}

function _render_available_demo_assets(frm) {
	const $wrapper = frm.fields_dict.available_demo_assets_html.$wrapper;
	$wrapper.html("");

	if (!frm.doc.item_code) return;

	frappe.call({
		method: "avientek.avientek.doctype.demo_unit_request.demo_unit_request.get_available_demo_assets",
		args: {
			item_code: frm.doc.item_code,
			company: frm.doc.company || "",
		},
		callback(r) {
			if (!r.message || !r.message.length) {
				$wrapper.html(`<div class="text-muted" style="padding: 10px;">
					${__("No matching demo assets found for this item. You may need to create an Asset Capitalization or Purchase Order.")}
				</div>`);
				return;
			}

			const assets = r.message;
			const free_count = assets.filter(a => a.custom_dam_status === "Free").length;

			let html = `<div style="
				background: var(--fg-color); border: 1px solid var(--border-color);
				border-radius: var(--border-radius-md); padding: 12px 15px;">
				<div style="font-weight: 600; font-size: var(--text-md); margin-bottom: 8px;">
					${__("Matching Demo Assets")} (${assets.length})
					<span class="indicator-pill ${free_count > 0 ? "green" : "orange"}" style="margin-left: 8px;">
						${free_count} ${__("Free")}
					</span>
				</div>
				<table class="table table-bordered table-sm" style="
					font-size: var(--text-sm); margin-bottom: 0;">
					<thead><tr>
						<th>${__("Asset")}</th>
						<th>${__("Asset Name")}</th>
						<th>${__("Part No")}</th>
						<th>${__("Status")}</th>
						<th>${__("Location / Customer")}</th>
						<th>${__("Country")}</th>
						<th>${__("Company")}</th>
					</tr></thead><tbody>`;

			assets.forEach(a => {
				const dam_status = a.custom_dam_status || "Free";
				const color_map = { "Free": "green", "On Demo": "orange", "Issued as Standby": "blue" };
				const badge_color = color_map[dam_status] || "gray";
				const location = a.custom_dam_customer || a.location || "\u2014";

				html += `<tr>
					<td>${frappe.utils.get_form_link("Asset", a.name, true)}</td>
					<td>${a.asset_name || ""}</td>
					<td>${a.custom_part_no || "\u2014"}</td>
					<td><span class="indicator-pill ${badge_color}">${__(dam_status)}</span></td>
					<td>${location}</td>
					<td>${a.custom_dam_country || "\u2014"}</td>
					<td>${a.company || ""}</td>
				</tr>`;
			});

			html += `</tbody></table></div>`;
			$wrapper.html(html);
		},
	});
}
