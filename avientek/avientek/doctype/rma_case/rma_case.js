frappe.ui.form.on("RMA Case", {

	refresh(frm) {
		frm.trigger("set_status_indicator");
		frm.trigger("add_action_buttons");
		frm.trigger("add_check_buttons");
		frm.trigger("render_standby_availability");

		// Filter asset field to demo assets only
		frm.set_query("demo_asset", () => ({
			filters: { custom_is_demo_asset: 1, docstatus: ["!=", 2] },
		}));
		frm.set_query("standby_unit", () => {
			const filters = { custom_is_demo_asset: 1, docstatus: ["!=", 2], custom_dam_status: "Free" };
			if (frm.doc.demo_asset) filters.name = ["!=", frm.doc.demo_asset];
			return { filters };
		});

		// Filter warranty_list by customer
		frm.set_query("warranty_list", () => {
			const filters = { docstatus: 1, status: "Under Warranty" };
			if (frm.doc.customer) filters.customer = frm.doc.customer;
			return { filters };
		});
	},

	// ─── Field Change Handlers ───

	item_code(frm) {
		if (frm.doc.item_code) {
			frm.trigger("render_standby_availability");
		}
	},

	warranty_list(frm) {
		if (!frm.doc.warranty_list) return;
		frappe.db.get_doc("Warranty List", frm.doc.warranty_list).then(wty => {
			frm.set_value("customer", wty.customer);
			frm.set_value("item_code", wty.item_code);
			frm.set_value("item_description", wty.item_name);
			frm.set_value("asset_serial_number", wty.serial_no || "");
			frm.set_value("warranty_status", wty.status === "Under Warranty" ? "Under Warranty" : "Expired");
			frm.set_value("warranty_expiry_date", wty.warranty_end_date);
			if (wty.company && !frm.doc.company) {
				frm.set_value("company", wty.company);
			}
		});
	},

	demo_asset(frm) {
		if (!frm.doc.demo_asset) return;
		frappe.db.get_value("Asset", frm.doc.demo_asset, [
			"gross_purchase_amount", "value_after_depreciation", "company", "item_code", "asset_name",
		], (r) => {
			if (!r) return;
			frm.set_value("gross_asset_value", r.gross_purchase_amount || 0);
			frm.set_value("net_asset_value", r.value_after_depreciation || 0);
			frm.set_value("accumulated_depreciation", (r.gross_purchase_amount || 0) - (r.value_after_depreciation || 0));
			if (r.item_code && !frm.doc.item_code) {
				frm.set_value("item_code", r.item_code);
			}
			if (r.asset_name && !frm.doc.item_description) {
				frm.set_value("item_description", r.asset_name);
			}
			if (r.company && !frm.doc.company) {
				frm.set_value("company", r.company);
			}
		});
	},

	customer(frm) {
		if (frm.doc.customer) {
			frappe.db.get_value("Customer", frm.doc.customer, "default_currency", (r) => {
				if (r && r.default_currency) {
					frm.set_value("repair_cost_currency", r.default_currency);
				}
			});
		}
	},

	// ─── Status Indicator ───

	set_status_indicator(frm) {
		const color_map = {
			"Open": "orange", "In Progress": "blue", "Pending Parts": "yellow",
			"Sent for Repair": "purple", "Repaired": "cyan", "Replaced": "green",
			"Closed": "green", "Cancelled": "red",
		};
		frm.page.set_indicator(frm.doc.status, color_map[frm.doc.status] || "gray");
	},

	// ─── Action Buttons ───

	add_action_buttons(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 1) return;

		// Issue Standby Unit — enhanced dialog
		if (!["Closed", "Cancelled"].includes(frm.doc.status) && !frm.doc.standby_unit) {
			frm.add_custom_button(__("Issue Standby Unit"), () => {
				frm.trigger("show_standby_dialog");
			}, __("Actions"));
		}

		// Return Standby Unit
		if (frm.doc.standby_unit && !["Closed", "Cancelled", "Replaced"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Return Standby Unit"), () => {
				frappe.confirm(
					__("Return standby unit <b>{0}</b>?", [frm.doc.standby_unit]),
					() => {
						frm.set_value("standby_unit", "");
						frm.set_value("standby_source", "");
						frm.save("Update");
						frappe.show_alert({ message: __("Standby unit returned"), indicator: "green" });
					}
				);
			}, __("Actions"));
		}

		// Mark as Closed
		if (!["Closed", "Cancelled"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Mark as Closed"), () => {
				frappe.confirm(__("Close this RMA Case?"), () => {
					frm.set_value("status", "Closed");
					frm.save("Update");
				});
			}, __("Actions"));
		}

		// Add Log Entry
		frm.add_custom_button(__("Add Log Entry"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Add Case Log Entry"),
				fields: [
					{
						fieldname: "log_type", fieldtype: "Select", label: __("Type"),
						options: "Note\nStatus Change\nCustomer Contact\nEngineer Update\nPart Ordered\nRepair Complete\nEscalation",
						default: "Note", reqd: 1,
					},
					{ fieldname: "description", fieldtype: "Small Text", label: __("Description"), reqd: 1 },
				],
				primary_action_label: __("Add"),
				primary_action(values) {
					frm.add_child("case_log", {
						log_type: values.log_type, description: values.description,
						logged_by: frappe.session.user, log_date: frappe.datetime.now_datetime(),
					});
					frm.refresh_field("case_log");
					frm.save("Update");
					d.hide();
					frappe.show_alert({ message: __("Log entry added"), indicator: "green" });
				},
			});
			d.show();
		}, __("Actions"));

		// View related Demo Movements
		if (frm.doc.demo_asset) {
			frm.add_custom_button(__("Demo Movements"), () => {
				frappe.set_route("List", "Demo Movement", { asset: frm.doc.demo_asset });
			}, __("View"));
		}
	},

	// ─── Check Buttons ───

	add_check_buttons(frm) {
		// Check Warranty
		if (frm.doc.customer || frm.doc.asset_serial_number || frm.doc.item_code) {
			frm.add_custom_button(__("Check Warranty"), () => {
				frappe.call({
					method: "avientek.avientek.doctype.rma_case.rma_case.check_warranty",
					args: {
						customer: frm.doc.customer || null,
						serial_no: frm.doc.asset_serial_number || null,
						item_code: frm.doc.item_code || null,
					},
					callback(r) {
						const data = r.message || [];
						if (!data.length) {
							frappe.msgprint(__("No warranty records found."));
							return;
						}

						let rows = data.map(w => {
							const badge = w.status === "Under Warranty"
								? `<span style="background:#D1FAE5;color:#065F46;padding:2px 8px;border-radius:10px;font-size:0.75rem;font-weight:700">${w.status}</span>`
								: `<span style="background:#FEE2E2;color:#991B1B;padding:2px 8px;border-radius:10px;font-size:0.75rem;font-weight:700">${w.status}</span>`;
							return `<tr>
								<td><a href="/app/warranty-list/${w.name}">${w.name}</a></td>
								<td>${badge}</td>
								<td>${w.item_code || ""}</td>
								<td>${w.serial_no || "\u2014"}</td>
								<td>${frappe.datetime.str_to_user(w.warranty_end_date)}</td>
								<td>${w.days_remaining || 0}</td>
								<td><button class="btn btn-xs btn-primary rma-wty-apply"
									data-name="${w.name}" data-status="${w.status}"
									data-end="${w.warranty_end_date}" data-item="${w.item_code || ""}"
									data-item-name="${w.item_name || ""}" data-serial="${w.serial_no || ""}"
									>${__("Apply")}</button></td>
							</tr>`;
						}).join("");

						const d = new frappe.ui.Dialog({ title: __("Warranty Lookup"), size: "extra-large" });
						d.$body.html(`
							<div style="overflow-x:auto">
							<table class="table table-bordered" style="font-size:0.85rem">
								<thead><tr>
									<th>${__("Warranty ID")}</th><th>${__("Status")}</th><th>${__("Item")}</th>
									<th>${__("Serial No")}</th><th>${__("Expiry")}</th><th>${__("Days Left")}</th><th></th>
								</tr></thead>
								<tbody>${rows}</tbody>
							</table></div>
						`);

						d.$body.find(".rma-wty-apply").on("click", function () {
							const $btn = $(this);
							frm.set_value("warranty_list", $btn.data("name"));
							frm.set_value("warranty_status", $btn.data("status") === "Under Warranty" ? "Under Warranty" : "Expired");
							frm.set_value("warranty_expiry_date", $btn.data("end"));
							if ($btn.data("item") && !frm.doc.item_code) frm.set_value("item_code", $btn.data("item"));
							if ($btn.data("item-name") && !frm.doc.item_description) frm.set_value("item_description", $btn.data("item-name"));
							if ($btn.data("serial") && !frm.doc.asset_serial_number) frm.set_value("asset_serial_number", $btn.data("serial"));
							d.hide();
							frappe.show_alert({ message: __("Warranty applied"), indicator: "green" });
						});
						d.show();
					},
				});
			}, __("Check"));
		}

		// Check Availability
		if (frm.doc.item_code) {
			frm.add_custom_button(__("Check Availability"), () => {
				frappe.call({
					method: "avientek.avientek.doctype.rma_case.rma_case.check_availability",
					args: { item_code: frm.doc.item_code, company: frm.doc.company || null },
					callback(r) {
						const data = r.message || {};
						const assets = data.demo_assets || [];
						const stock = data.stock || [];
						let html = "";

						html += `<h5 style="margin-top:0">${__("Free Demo Assets")}</h5>`;
						if (assets.length) {
							html += `<table class="table table-bordered" style="font-size:0.85rem">
								<thead><tr><th>${__("Asset")}</th><th>${__("Name")}</th><th>${__("Location")}</th><th>${__("Company")}</th></tr></thead><tbody>`;
							assets.forEach(a => {
								html += `<tr><td><a href="/app/asset/${a.name}">${a.name}</a></td>
									<td>${a.asset_name || ""}</td><td>${a.location || "\u2014"}</td><td>${a.company || ""}</td></tr>`;
							});
							html += `</tbody></table>`;
						} else {
							html += `<p style="color:var(--text-muted)">${__("No free demo assets found.")}</p>`;
						}

						html += `<h5>${__("Stock Availability")}</h5>`;
						if (stock.length) {
							html += `<table class="table table-bordered" style="font-size:0.85rem">
								<thead><tr><th>${__("Warehouse")}</th><th>${__("Available")}</th><th>${__("Reserved")}</th></tr></thead><tbody>`;
							stock.forEach(s => {
								const avail = (s.actual_qty || 0) - (s.reserved_qty || 0);
								html += `<tr><td>${s.warehouse}</td>
									<td style="font-weight:700;color:${avail > 0 ? '#059669' : '#DC2626'}">${avail}</td>
									<td>${s.reserved_qty || 0}</td></tr>`;
							});
							html += `</tbody></table>`;
						} else {
							html += `<p style="color:var(--text-muted)">${__("No stock found.")}</p>`;
						}

						const d = new frappe.ui.Dialog({ title: __("Availability — {0}", [frm.doc.item_code]), size: "large" });
						d.$body.html(`<div style="padding:8px">${html}</div>`);
						d.show();
					},
				});
			}, __("Check"));
		}
	},

	// ─── Standby Availability HTML Panel ───

	render_standby_availability(frm) {
		const $wrapper = frm.fields_dict.standby_availability_html?.$wrapper;
		if (!$wrapper) return;

		if (!frm.doc.item_code || frm.doc.standby_unit) {
			$wrapper.html("");
			return;
		}

		$wrapper.html(`<div style="color:var(--text-muted);font-size:0.85rem;padding:8px 0">${__("Checking availability...")}</div>`);

		frappe.call({
			method: "avientek.avientek.doctype.rma_case.rma_case.check_availability",
			args: { item_code: frm.doc.item_code, company: frm.doc.company || null },
			callback(r) {
				const data = r.message || {};
				const assets = data.demo_assets || [];
				const stock = data.stock || [];
				const total_stock = stock.reduce((sum, s) => sum + Math.max((s.actual_qty || 0) - (s.reserved_qty || 0), 0), 0);

				let html = `<div style="font-size:0.85rem;padding:4px 0">`;
				html += `<div style="font-weight:700;margin-bottom:6px">${__("Standby Options")}</div>`;

				if (assets.length) {
					html += `<div style="color:#059669;font-weight:600">\u2713 ${assets.length} ${__("free demo asset(s)")}</div>`;
				} else {
					html += `<div style="color:#DC2626">\u2717 ${__("No free demo assets")}</div>`;
				}

				if (total_stock > 0) {
					html += `<div style="color:#2563EB;font-weight:600">\u2713 ${total_stock} ${__("in stock")} — ${__("can capitalize")}</div>`;
				} else {
					html += `<div style="color:var(--text-muted)">\u2717 ${__("No stock available")}</div>`;
				}

				html += `</div>`;
				$wrapper.html(html);
			},
		});
	},

	// ─── Enhanced Standby Issue Dialog ───

	show_standby_dialog(frm) {
		frappe.call({
			method: "avientek.avientek.doctype.rma_case.rma_case.check_availability",
			args: { item_code: frm.doc.item_code || null, company: frm.doc.company || null },
			callback(r) {
				const data = r.message || {};
				const assets = data.demo_assets || [];
				const stock = data.stock || [];
				const has_stock = stock.some(s => (s.actual_qty || 0) - (s.reserved_qty || 0) > 0);

				const d = new frappe.ui.Dialog({
					title: __("Issue Standby Unit"),
					fields: [
						{
							fieldname: "source", fieldtype: "Select", label: __("Standby Source"),
							options: "\nExisting Demo Asset\nCapitalize from Stock", reqd: 1,
							change() {
								const val = d.get_value("source");
								d.set_df_property("standby_asset", "hidden", val !== "Existing Demo Asset");
								d.set_df_property("cap_section", "hidden", val !== "Capitalize from Stock");
							},
						},
						{ fieldtype: "Section Break" },
						{
							fieldname: "standby_asset", fieldtype: "Link", options: "Asset",
							label: __("Select Demo Asset"), hidden: 1,
							get_query: () => {
								const filters = { custom_is_demo_asset: 1, docstatus: ["!=", 2], custom_dam_status: "Free" };
								if (frm.doc.item_code) filters.item_code = frm.doc.item_code;
								if (frm.doc.demo_asset) filters.name = ["!=", frm.doc.demo_asset];
								return { filters };
							},
						},
						{ fieldname: "cap_section", fieldtype: "Section Break", label: __("Capitalize from Stock"), hidden: 1 },
						{
							fieldname: "stock_info", fieldtype: "HTML",
						},
						{
							fieldname: "warehouse", fieldtype: "Link", options: "Warehouse",
							label: __("Source Warehouse"),
							get_query: () => ({ filters: { company: frm.doc.company } }),
						},
						{
							fieldname: "asset_location", fieldtype: "Link", options: "Location",
							label: __("Asset Location"),
						},
					],
					primary_action_label: __("Issue"),
					primary_action(values) {
						if (values.source === "Existing Demo Asset") {
							if (!values.standby_asset) { frappe.throw(__("Select a demo asset")); return; }
							frm.set_value("standby_unit", values.standby_asset);
							frm.set_value("standby_source", "Existing Demo Asset");
							frm.save("Update");
							d.hide();
							frappe.show_alert({ message: __("Standby unit assigned"), indicator: "green" });

						} else if (values.source === "Capitalize from Stock") {
							if (!values.warehouse) { frappe.throw(__("Select source warehouse")); return; }
							if (!values.asset_location) { frappe.throw(__("Select asset location")); return; }
							d.hide();
							frappe.call({
								method: "avientek.avientek.doctype.rma_case.rma_case.create_standby_capitalization",
								args: {
									rma_case: frm.doc.name,
									item_code: frm.doc.item_code,
									company: frm.doc.company,
									warehouse: values.warehouse,
									asset_location: values.asset_location,
								},
								callback(r2) {
									if (r2.message) {
										frappe.show_alert({
											message: __("Asset Capitalization {0} created. Submit it to generate the standby asset.", [
												`<a href="/app/asset-capitalization/${r2.message}">${r2.message}</a>`
											]),
											indicator: "blue",
										});
										frm.reload_doc();
									}
								},
							});
						}
					},
				});

				// Populate stock info
				if (has_stock) {
					const stock_rows = stock
						.filter(s => (s.actual_qty || 0) - (s.reserved_qty || 0) > 0)
						.map(s => `<div style="display:flex;justify-content:space-between;padding:2px 0">
							<span>${s.warehouse}</span>
							<span style="font-weight:700;color:#059669">${(s.actual_qty || 0) - (s.reserved_qty || 0)}</span>
						</div>`).join("");
					d.fields_dict.stock_info.$wrapper.html(
						`<div style="background:var(--bg-light-gray);border-radius:8px;padding:12px;font-size:0.85rem">
							<div style="font-weight:700;margin-bottom:6px">${__("Available Stock")}</div>
							${stock_rows}
							<div style="color:var(--text-muted);margin-top:8px;font-size:0.8rem">
								${__("Creates an Asset Capitalization (draft) to convert stock into a demo asset for standby.")}
							</div>
						</div>`
					);
				}

				// Auto-select source
				if (assets.length) {
					d.set_value("source", "Existing Demo Asset");
				} else if (has_stock) {
					d.set_value("source", "Capitalize from Stock");
				}

				d.show();
			},
		});
	},
});
