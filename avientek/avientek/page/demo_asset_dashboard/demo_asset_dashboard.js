frappe.pages["demo-asset-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Demo Asset Management",
		single_column: true,
	});

	frappe.dam_dashboard = new DamDashboard(page);
};

frappe.pages["demo-asset-dashboard"].on_page_show = function () {
	if (frappe.dam_dashboard) {
		frappe.dam_dashboard.refresh();
	}
};

class DamDashboard {
	constructor(page) {
		this.page = page;
		this.company = null;
		this.$main = $(this.page.main);
		this.setup_page();
	}

	setup_page() {
		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "octicon octicon-sync");

		// Company filter
		this.company_field = this.page.add_field({
			fieldname: "company",
			fieldtype: "Link",
			options: "Company",
			label: __("Company"),
			default: frappe.defaults.get_default("company"),
			change: () => {
				this.company = this.company_field.get_value();
				this.refresh();
			},
		});
		this.company = this.company_field.get_value();

		this.$main.html(this.get_skeleton());
		this.refresh();
	}

	get_skeleton() {
		return `
		<div class="dam-dashboard">
			<div class="dam-stat-row" id="dam-stats"></div>
			<div class="dam-overdue-banner" id="dam-overdue" style="display:none"></div>
			<div class="dam-content-row">
				<div class="dam-panel dam-movements" id="dam-movements"></div>
				<div class="dam-panel dam-quick-actions" id="dam-quick-actions"></div>
			</div>
		</div>`;
	}

	refresh() {
		const company = this.company || null;
		Promise.all([
			frappe.call({ method: "avientek.avientek.page.demo_asset_dashboard.demo_asset_dashboard.get_dashboard_stats", args: { company } }),
			frappe.call({ method: "avientek.avientek.page.demo_asset_dashboard.demo_asset_dashboard.get_overdue_assets", args: { company } }),
			frappe.call({ method: "avientek.avientek.page.demo_asset_dashboard.demo_asset_dashboard.get_recent_movements", args: { company, limit: 8 } }),
		]).then(([stats_r, overdue_r, movements_r]) => {
			this.render_stats(stats_r.message || {});
			this.render_overdue_banner(overdue_r.message || []);
			this.render_movements(movements_r.message || []);
			this.render_quick_actions();
		});
	}

	render_stats(data) {
		const cards = [
			{ label: "Total Demo Assets", value: data.total || 0, color: "#2563EB", icon: "assets", route: ["List", "Asset", { custom_is_demo_asset: 1 }] },
			{ label: "Out for Demo", value: data.out_for_demo || 0, color: "#EA580C", icon: "arrow-up-right", route: ["List", "Asset", { custom_dam_status: "On Demo" }] },
			{ label: "Overdue", value: data.overdue || 0, color: "#DC2626", icon: "alert", route: ["demo-asset-dashboard"] },
			{ label: "Free / Available", value: data.free || 0, color: "#059669", icon: "circle", route: ["List", "Asset", { custom_dam_status: "Free", custom_is_demo_asset: 1 }] },
			{ label: "Open RMA Cases", value: data.open_rma || 0, color: "#D97706", icon: "refresh", route: ["List", "RMA Case", {}] },
		];

		const html = cards.map(c => `
			<div class="dam-stat-card" style="border-top: 3px solid ${c.color}; cursor:pointer"
				data-route='${JSON.stringify(c.route)}'>
				<div class="dam-stat-value" style="color:${c.color}">${c.value}</div>
				<div class="dam-stat-label">${__(c.label)}</div>
			</div>`).join("");

		this.$main.find("#dam-stats").html(html);

		// Card click routing
		this.$main.find(".dam-stat-card").on("click", function () {
			const route = $(this).data("route");
			if (route) frappe.set_route(...route);
		});
	}

	render_overdue_banner(overdue) {
		const $banner = this.$main.find("#dam-overdue");
		if (!overdue.length) {
			$banner.hide();
			return;
		}
		const names = overdue.slice(0, 3).map(o =>
			`<a href="/app/demo-movement?asset=${o.asset}">
				${o.asset_name} @ ${o.customer} (${o.days_overdue}d overdue)
			</a>`
		).join(" &middot; ");

		$banner.show().html(`
			<div class="dam-overdue-content">
				<span class="dam-overdue-icon">⚠</span>
				<span>
					<strong>${overdue.length} demo unit${overdue.length > 1 ? "s" : ""} overdue for return</strong>
					<span class="dam-overdue-names">${names}</span>
				</span>
				<button class="btn btn-danger btn-xs dam-view-all">${__("View All")}</button>
			</div>`);

		$banner.find(".dam-view-all").on("click", () => {
			frappe.set_route("List", "Demo Movement", {
				movement_type: "Move Out",
				status: "Overdue",
			});
		});
	}

	render_movements(movements) {
		if (!movements.length) {
			this.$main.find("#dam-movements").html(`
				<div class="dam-panel-header">${__("Recent Asset Movements")}</div>
				<div class="dam-empty">${__("No movements yet")}</div>`);
			return;
		}

		const rows = movements.map(m => {
			const status_color = { Open: "orange", Returned: "green", Overdue: "red" }[m.status] || "gray";
			return `
			<tr class="dam-movement-row" onclick="frappe.set_route('Form','Demo Movement','${m.name}')"
				style="cursor:pointer">
				<td>
					<div class="dam-asset-name">${m.asset_name || m.asset}</div>
					<div class="dam-asset-sub">${m.asset}</div>
				</td>
				<td>${m.customer || "—"}</td>
				<td>${frappe.datetime.str_to_user(m.movement_date) || "—"}</td>
				<td>
					<span class="indicator-pill ${status_color}">${__(m.status)}</span>
				</td>
			</tr>`;
		}).join("");

		this.$main.find("#dam-movements").html(`
			<div class="dam-panel-header">
				${__("Recent Asset Movements")}
				<a class="dam-see-all" onclick="frappe.set_route('List','Demo Movement',{})">${__("See All")}</a>
			</div>
			<table class="dam-table">
				<thead>
					<tr>
						<th>${__("Asset")}</th>
						<th>${__("Customer / Site")}</th>
						<th>${__("Date")}</th>
						<th>${__("Status")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>`);
	}

	render_quick_actions() {
		const actions = [
			{ label: "Quick Create Demo Asset", icon: "+", color: "#7C3AED", action: () => this.quick_create_demo_asset() },
			{ label: "New Demo Movement", icon: "↕", color: "#2563EB", action: () => frappe.new_doc("Demo Movement") },
			{ label: "Open RMA Case", icon: "⟳", color: "#D97706", action: () => frappe.new_doc("RMA Case") },
			{ label: "All Demo Assets", icon: "◆", color: "#059669", action: () => frappe.set_route("List", "Asset", { custom_is_demo_asset: 1 }) },
			{ label: "Items Out for Demo", icon: "↗", color: "#EA580C", action: () => frappe.set_route("List", "Asset", { custom_dam_status: "On Demo" }) },
			{ label: "View Overdue", icon: "⚠", color: "#DC2626", action: () => frappe.set_route("List", "Demo Movement", { status: "Overdue" }) },
		];

		const html = actions.map(a => `
			<div class="dam-quick-action" style="cursor:pointer; border-left: 3px solid ${a.color}">
				<span class="dam-qa-icon" style="color:${a.color}">${a.icon}</span>
				<span class="dam-qa-label">${__(a.label)}</span>
			</div>`).join("");

		this.$main.find("#dam-quick-actions").html(`
			<div class="dam-panel-header">${__("Quick Actions")}</div>
			${html}`);

		actions.forEach((a, i) => {
			this.$main.find(".dam-quick-action").eq(i).on("click", a.action);
		});
	}

	quick_create_demo_asset() {
		const d = new frappe.ui.Dialog({
			title: __("Quick Create Demo Asset"),
			fields: [
				{
					fieldname: "item_code",
					fieldtype: "Link",
					label: __("Item"),
					options: "Item",
					reqd: 1,
					onchange: () => {
						const item = d.get_value("item_code");
						if (!item) return;
						frappe.db.get_value("Item", item, ["item_name", "asset_category"], r => {
							if (!r) return;
							if (!d.get_value("asset_name") && r.item_name) {
								d.set_value("asset_name", r.item_name);
							}
							if (r.asset_category) d.set_value("asset_category", r.asset_category);
						});
					},
				},
				{
					fieldname: "asset_name",
					fieldtype: "Data",
					label: __("Asset Name"),
					reqd: 1,
				},
				{
					fieldname: "asset_category",
					fieldtype: "Link",
					label: __("Asset Category"),
					options: "Asset Category",
					reqd: 1,
				},
				{ fieldname: "col_break_1", fieldtype: "Column Break" },
				{
					fieldname: "company",
					fieldtype: "Link",
					label: __("Company"),
					options: "Company",
					reqd: 1,
					default: frappe.defaults.get_default("company"),
				},
				{
					fieldname: "location",
					fieldtype: "Link",
					label: __("Target Asset Location"),
					options: "Location",
					reqd: 1,
				},
				{ fieldname: "sec_break_stock", fieldtype: "Section Break", label: __("Consumed Stock") },
				{
					fieldname: "warehouse",
					fieldtype: "Link",
					label: __("Warehouse"),
					options: "Warehouse",
					reqd: 1,
					get_query: () => {
						const company = d.get_value("company");
						return company ? { filters: { company } } : {};
					},
				},
				{
					fieldname: "qty",
					fieldtype: "Float",
					label: __("Quantity"),
					default: 1,
					reqd: 1,
				},
				{
					fieldname: "posting_date",
					fieldtype: "Date",
					label: __("Posting Date"),
					reqd: 1,
					default: frappe.datetime.get_today(),
				},
			],
			primary_action_label: __("Create Asset"),
			primary_action(values) {
				frappe.call({
					method: "avientek.avientek.page.demo_asset_dashboard.demo_asset_dashboard.create_demo_asset",
					args: {
						item_code: values.item_code,
						asset_name: values.asset_name,
						asset_category: values.asset_category,
						company: values.company,
						location: values.location,
						purchase_date: values.posting_date,
						warehouse: values.warehouse,
						qty: values.qty || 1,
					},
					callback(r) {
						if (r.message) {
							d.hide();
							frappe.show_alert({ message: __("Demo Asset {0} created", [r.message]), indicator: "green" });
							frappe.set_route("Form", "Asset", r.message);
						}
					},
				});
			},
		});
		d.show();
	}
}