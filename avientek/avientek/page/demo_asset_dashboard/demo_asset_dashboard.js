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

const DAM_API = "avientek.avientek.page.demo_asset_dashboard.demo_asset_dashboard";

class DamDashboard {
	constructor(page) {
		this.page = page;
		this.company = null;
		this.current_view = "dashboard";
		this.asset_filter = "All";
		this.$main = $(this.page.main);
		this.setup_page();
	}

	setup_page() {
		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "octicon octicon-sync");

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
		this.$sidebar = this.$main.find(".dam-sidebar");
		this.$content = this.$main.find(".dam-main-content");

		this.render_sidebar();
		this.refresh();
	}

	get_skeleton() {
		return `
		<div class="dam-app">
			<aside class="dam-sidebar"></aside>
			<main class="dam-main-content"></main>
		</div>`;
	}

	render_sidebar() {
		const nav = [
			{ id: "dashboard", label: __("Dashboard"), icon: "\u2B21" },
			{ id: "demo-assets", label: __("Demo Assets"), icon: "\u25C8" },
			{ id: "items-out", label: __("Items Out for Demo"), icon: "\u2197" },
			{ id: "divider1", type: "divider" },
			{ id: "new-movement", label: __("New Movement"), icon: "\u21C4", action: () => frappe.new_doc("Demo Movement") },
			{ id: "divider2", type: "divider" },
			{ id: "ack", label: __("Acknowledgement"), icon: "\u2726", action: () => frappe.set_route("List", "Demo Movement", { docstatus: 1 }) },
		];

		let html = `
			<ul class="dam-nav">`;

		nav.forEach(n => {
			if (n.type === "divider") {
				html += `<li class="dam-nav-divider"></li>`;
			} else {
				const active = n.id === this.current_view ? " active" : "";
				html += `
				<li class="dam-nav-item${active}" data-view="${n.id}" data-is-action="${n.action ? 1 : 0}">
					<span class="dam-nav-icon">${n.icon}</span>
					${n.label}
				</li>`;
			}
		});

		html += `</ul>`;
		this.$sidebar.html(html);

		// Bind click handlers
		const self = this;
		this.$sidebar.find(".dam-nav-item").on("click", function () {
			const view = $(this).data("view");
			const is_action = $(this).data("is-action");
			if (is_action) {
				const item = nav.find(n => n.id === view);
				if (item && item.action) item.action();
			} else {
				self.switch_view(view);
			}
		});
	}

	switch_view(view_key) {
		this.current_view = view_key;
		this.$sidebar.find(".dam-nav-item").removeClass("active");
		this.$sidebar.find(`[data-view="${view_key}"]`).addClass("active");
		this.$content.empty();
		this.refresh_current();
	}

	refresh() {
		this.refresh_current();
	}

	refresh_current() {
		switch (this.current_view) {
			case "dashboard": this.refresh_dashboard(); break;
			case "demo-assets": this.refresh_demo_assets(); break;
			case "items-out": this.refresh_items_out(); break;
		}
	}

	// ─── Dashboard View ───

	refresh_dashboard() {
		const company = this.company || null;
		this.$content.html(`
			<div class="dam-dashboard">
				<div class="dam-stat-row" id="dam-stats"></div>
				<div class="dam-overdue-banner" id="dam-overdue" style="display:none"></div>
				<div class="dam-panel dam-movements" id="dam-movements"></div>
			</div>`);

		Promise.all([
			frappe.call({ method: `${DAM_API}.get_dashboard_stats`, args: { company } }),
			frappe.call({ method: `${DAM_API}.get_overdue_assets`, args: { company } }),
			frappe.call({ method: `${DAM_API}.get_recent_movements`, args: { company, limit: 8 } }),
		]).then(([stats_r, overdue_r, movements_r]) => {
			this.render_stats(stats_r.message || {});
			this.render_overdue_banner(overdue_r.message || []);
			this.render_movements(movements_r.message || []);
		});
	}

	render_stats(data) {
		const cards = [
			{ label: "Total Demo Assets", value: data.total || 0, color: "#2563EB", icon: "\u25C8", route: ["List", "Asset", { custom_is_demo_asset: 1 }] },
			{ label: "Out for Demo", value: data.out_for_demo || 0, color: "#EA580C", icon: "\u2197", route: ["List", "Asset", { custom_dam_status: "On Demo" }] },
			{ label: "Overdue", value: data.overdue || 0, color: "#DC2626", icon: "\u26A0", route: null },
			{ label: "Free / Available", value: data.free || 0, color: "#059669", icon: "\u25CB", route: ["List", "Asset", { custom_dam_status: "Free", custom_is_demo_asset: 1 }] },
		];

		const html = cards.map(c => `
			<div class="dam-stat-card" style="border-top: 3px solid ${c.color}; cursor:pointer"
				data-route='${JSON.stringify(c.route)}'>
				<div class="dam-stat-value" style="color:${c.color}">${c.value}</div>
				<div class="dam-stat-label">${__(c.label)}</div>
			</div>`).join("");

		this.$content.find("#dam-stats").html(html);

		const self = this;
		this.$content.find(".dam-stat-card").on("click", function () {
			const route = $(this).data("route");
			if (route) {
				frappe.set_route(...route);
			} else {
				// Overdue or RMA — switch to internal view
				const label = $(this).find(".dam-stat-label").text();
				if (label.includes("Overdue")) self.switch_view("items-out");
			}
		});
	}

	render_overdue_banner(overdue) {
		const $banner = this.$content.find("#dam-overdue");
		if (!overdue.length) {
			$banner.hide();
			return;
		}
		const names = overdue.slice(0, 3).map(o =>
			`${o.asset_name} @ ${o.customer}`
		).join(" \u00B7 ");

		$banner.show().html(`
			<div class="dam-overdue-content">
				<span class="dam-overdue-icon">\u26A0\uFE0F</span>
				<span>
					<strong>${overdue.length} demo unit${overdue.length > 1 ? "s" : ""} overdue for return</strong>
					<span class="dam-overdue-names">${names}</span>
				</span>
				<button class="btn btn-danger btn-xs dam-view-all">${__("View All")}</button>
			</div>`);

		$banner.find(".dam-view-all").on("click", () => this.switch_view("items-out"));
	}

	render_movements(movements) {
		if (!movements.length) {
			this.$content.find("#dam-movements").html(`
				<div class="dam-panel-header">${__("Recent Asset Movements")}</div>
				<div class="dam-empty">${__("No movements yet")}</div>`);
			return;
		}

		const rows = movements.map(m => {
			const display_status = (m.status === "Returned" || m.status === "Completed")
				? m.status
				: (m.custom_dam_status || m.status);
			const status_color = {
				"On Demo": "orange",
				"Issued as Standby": "blue",
				"Free": "green",
				"Returned": "green",
				"Completed": "green",
				"Open": "orange",
				"Overdue": "red",
			}[display_status] || "gray";
			return `
			<tr class="dam-movement-row" onclick="frappe.set_route('Form','Demo Movement','${m.name}')"
				style="cursor:pointer">
				<td>
					<div class="dam-asset-name">${m.asset_name || m.asset}</div>
					<div class="dam-asset-sub">${m.asset}</div>
				</td>
				<td>${m.customer || "\u2014"}</td>
				<td>${frappe.datetime.str_to_user(m.movement_date) || "\u2014"}</td>
				<td>
					<span class="indicator-pill ${status_color}">${__(display_status).toUpperCase()}</span>
				</td>
			</tr>`;
		}).join("");

		this.$content.find("#dam-movements").html(`
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

	// ─── Demo Assets View ───

	refresh_demo_assets() {
		const company = this.company || null;
		const filter = this.asset_filter || "All";

		this.$content.html(`
			<div class="dam-view-header">
				<div class="dam-view-title">
					<h2>${__("Demo Asset Register")}</h2>
					<p>${__("All capitalized demo equipment \u2014 UAE & KSA")}</p>
				</div>
				<button class="dam-btn-primary" id="dam-capitalize-btn">+ ${__("Capitalize New Asset")}</button>
			</div>
			<div class="dam-filter-row" id="dam-asset-filters"></div>
			<div class="dam-table-card" id="dam-asset-table">
				<div class="dam-empty">${__("Loading...")}</div>
			</div>`);

		this.$content.find("#dam-capitalize-btn").on("click", () => frappe.new_doc("Asset Capitalization"));

		// Render filter pills
		const filters = ["All", "Free", "On Demo", "Issued as Standby"];
		const pills = filters.map(f =>
			`<span class="dam-filter-pill${f === filter ? " active" : ""}" data-filter="${f}">${__(f)}</span>`
		).join("");
		this.$content.find("#dam-asset-filters").html(pills);

		this.$content.find(".dam-filter-pill").on("click", (e) => {
			this.asset_filter = $(e.currentTarget).data("filter");
			this.refresh_demo_assets();
		});

		frappe.call({
			method: `${DAM_API}.get_demo_assets`,
			args: { company, status_filter: filter },
		}).then(r => {
			this.render_demo_assets(r.message || []);
		});
	}

	render_demo_assets(data) {
		const $table = this.$content.find("#dam-asset-table");

		if (!data.length) {
			$table.html(`<div class="dam-empty">${__("No demo assets found")}</div>`);
			return;
		}

		const rows = data.map(a => {
			const status = a.custom_dam_status || "Free";
			const badge_cls = {
				"Free": "dam-badge-free",
				"On Demo": "dam-badge-on-demo",
				"Issued as Standby": "dam-badge-standby",
			}[status] || "";

			let days_html = `<span style="color:var(--text-muted)">\u2014</span>`;
			if (a.days_out !== null && a.days_out !== undefined) {
				const cls = a.is_overdue ? "dam-days-overdue" : a.days_out > 10 ? "dam-days-warning" : "dam-days-ok";
				days_html = `<span class="dam-days-out ${cls}">${a.days_out}d${a.is_overdue ? " \u26A0" : ""}</span>`;
			}

			const location = a.custom_dam_customer || a.location || "\u2014";
			const serial = a.custom_serial_no || "\u2014";
			const part_no = a.custom_part_no || "\u2014";
			const owned_by = a.asset_owner_company || "\u2014";
			const country = a.custom_dam_country || "\u2014";
			const notes = a.custom_dam_notes || "";
			let actions = `<button class="dam-btn-view" onclick="frappe.set_route('Form','Asset','${a.name}')">${__("View")}</button>`;
			if (status === "Free") {
				actions += ` <button class="dam-btn-moveout" onclick="frappe.new_doc('Demo Movement',{asset:'${a.name}',movement_type:'Move Out',company:'${a.company}'})">${__("Move Out")}</button>`;
			}

			return `
			<tr class="${a.is_overdue ? "dam-row-overdue" : ""}">
				<td><span class="dam-badge ${badge_cls}">${__(status).toUpperCase()}</span></td>
				<td>${country}</td>
				<td style="color:var(--text-muted); font-size:0.85rem">${location}</td>
				<td>
					<div class="dam-asset-name">${a.brand || "\u2014"}</div>
				</td>
				<td>
					<div class="dam-asset-sub">${a.asset_name || a.item_code || ""}</div>
				</td>
				<td class="dam-mono-cell">${serial}</td>
				<td class="dam-mono-cell">${part_no}</td>
				<td>${owned_by}</td>
				<td style="color:var(--text-muted); font-size:0.82rem; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap" title="${frappe.utils.escape_html(notes)}">${notes || "\u2014"}</td>
				<td>${days_html}</td>
				<td><div style="display:flex;gap:6px">${actions}</div></td>
			</tr>`;
		}).join("");

		$table.html(`
			<div style="overflow-x:auto">
			<table class="dam-table">
				<thead><tr>
					<th>${__("Status")}</th>
					<th>${__("Country")}</th>
					<th>${__("Location")}</th>
					<th>${__("Brand")}</th>
					<th>${__("Model")}</th>
					<th>${__("Serial No")}</th>
					<th>${__("Part No")}</th>
					<th>${__("Owned By")}</th>
					<th>${__("Note")}</th>
					<th>${__("Days Out")}</th>
					<th>${__("Actions")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
			</div>`);
	}

	// ─── Items Out for Demo View ───

	refresh_items_out() {
		const company = this.company || null;

		this.$content.html(`
			<div class="dam-view-header">
				<div class="dam-view-title">
					<h2>${__("Items Out for Demo")}</h2>
					<p>${__("Live tracker \u2014 units currently at customer sites")}</p>
				</div>
			</div>
			<div class="dam-table-card" id="dam-out-table">
				<div class="dam-empty">${__("Loading...")}</div>
			</div>`);

		frappe.call({
			method: `${DAM_API}.get_items_out_for_demo`,
			args: { company },
		}).then(r => {
			this.render_items_out(r.message || []);
		});
	}

	render_items_out(data) {
		const $table = this.$content.find("#dam-out-table");

		if (!data.length) {
			$table.html(`<div class="dam-empty">${__("No assets currently out for demo")}</div>`);
			return;
		}

		const rows = data.map(a => {
			const is_overdue = a.is_overdue;
			const days_cls = is_overdue ? "dam-days-overdue" : a.days_outstanding > 10 ? "dam-days-warning" : "dam-days-ok";

			let return_date_html = "\u2014";
			if (a.expected_return_date) {
				const date_str = frappe.datetime.str_to_user(a.expected_return_date);
				if (is_overdue) {
					return_date_html = `<span style="color:#DC2626; font-weight:700">${date_str} <span style="font-size:0.72rem">OVERDUE</span></span>`;
				} else {
					return_date_html = date_str;
				}
			}

			const status_badge = is_overdue
				? `<span class="dam-badge dam-badge-overdue">OVERDUE</span>`
				: `<span class="dam-badge dam-badge-on-demo">ON DEMO</span>`;

			return `
			<tr class="${is_overdue ? "dam-row-overdue" : ""}" style="cursor:pointer"
				onclick="frappe.set_route('Form','Demo Movement','${a.movement_name}')">
				<td>
					<div class="dam-asset-name">${a.asset_name || a.asset}</div>
					<div class="dam-asset-sub dam-asset-id">${a.asset}</div>
				</td>
				<td style="font-weight:500">${a.customer || "\u2014"}</td>
				<td style="color:var(--text-muted)">${frappe.datetime.str_to_user(a.movement_date) || "\u2014"}</td>
				<td>${return_date_html}</td>
				<td><span class="dam-days-out ${days_cls}">${a.days_outstanding}d</span></td>
				<td style="color:var(--text-muted)">${a.requested_salesperson || "\u2014"}</td>
				<td>
					<div style="display:flex; gap:6px; align-items:center">
						${status_badge}
						<button class="dam-btn-return" data-asset="${a.asset}" data-movement="${a.movement_name}"
							onclick="event.stopPropagation(); window._dam_return_asset(this.dataset.movement)">
							${__("Return")}
						</button>
					</div>
				</td>
			</tr>`;
		}).join("");

		$table.html(`
			<table class="dam-table">
				<thead><tr>
					<th>${__("Asset")}</th>
					<th>${__("Customer / Site")}</th>
					<th>${__("Movement Date")}</th>
					<th>${__("Expected Return")}</th>
					<th>${__("Days Outstanding")}</th>
					<th>${__("Salesperson")}</th>
					<th>${__("Status")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>`);
	}

}

// Helper: short company name for badge
function _get_company_short(company) {
	if (!company) return "\u2014";
	if (company.includes("FZCO") || company.includes("LLC")) return "UAE";
	if (company.includes("WLL") || company.includes("KSA")) return "KSA";
	return company.split(" ")[0];
}

// Helper: create Return movement with all fields from the original Move Out
window._dam_return_asset = function (movement_name) {
	frappe.db.get_value("Demo Movement", movement_name, [
		"asset", "company", "customer", "contact_person", "mobile",
		"email", "country", "purpose", "requested_salesperson", "serial_number",
	], (r) => {
		if (!r) return;
		frappe.new_doc("Demo Movement", {
			asset: r.asset,
			movement_type: "Return",
			company: r.company,
			customer: r.customer,
			contact_person: r.contact_person,
			mobile: r.mobile,
			email: r.email,
			country: r.country,
			purpose: r.purpose,
			requested_salesperson: r.requested_salesperson,
			serial_number: r.serial_number,
		});
	});
};
