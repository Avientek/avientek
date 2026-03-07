frappe.pages["rma-case-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "RMA Case Management",
		single_column: true,
	});

	frappe.rma_dashboard = new RmaDashboard(page);
};

frappe.pages["rma-case-dashboard"].on_page_show = function () {
	if (frappe.rma_dashboard) {
		frappe.rma_dashboard.refresh();
	}
};

const RMA_API = "avientek.avientek.page.rma_case_dashboard.rma_case_dashboard";

class RmaDashboard {
	constructor(page) {
		this.page = page;
		this.company = null;
		this.current_view = "dashboard";
		this.case_filter = "All";
		this.warranty_filter = "All";
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
		this.$sidebar = this.$main.find(".rma-sidebar");
		this.$content = this.$main.find(".rma-main-content");

		this.render_sidebar();
		this.refresh();
	}

	get_skeleton() {
		return `
		<div class="rma-app">
			<aside class="rma-sidebar"></aside>
			<main class="rma-main-content"></main>
		</div>`;
	}

	render_sidebar() {
		const nav = [
			{ id: "dashboard", label: __("Dashboard"), icon: "\u2B21" },
			{ id: "all-cases", label: __("All Cases"), icon: "\u21BA" },
			{ id: "warranties", label: __("Warranties"), icon: "\u2691" },
			{ id: "divider1", type: "divider" },
			{ id: "new-rma", label: __("New RMA Case"), icon: "\uFF0B", action: () => frappe.new_doc("RMA Case") },
		];

		let html = `<ul class="rma-nav">`;

		nav.forEach(n => {
			if (n.type === "divider") {
				html += `<li class="rma-nav-divider"></li>`;
			} else {
				const active = n.id === this.current_view ? " active" : "";
				html += `
				<li class="rma-nav-item${active}" data-view="${n.id}" data-is-action="${n.action ? 1 : 0}">
					<span class="rma-nav-icon">${n.icon}</span>
					${n.label}
				</li>`;
			}
		});

		html += `</ul>`;
		this.$sidebar.html(html);

		const self = this;
		this.$sidebar.find(".rma-nav-item").on("click", function () {
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
		this.$sidebar.find(".rma-nav-item").removeClass("active");
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
			case "all-cases": this.refresh_all_cases(); break;
			case "warranties": this.refresh_warranties(); break;
		}
	}

	// ─── Dashboard View ───

	refresh_dashboard() {
		const company = this.company || null;
		this.$content.html(`
			<div class="rma-dashboard">
				<div class="rma-stat-row" id="rma-stats"></div>
				<div class="rma-view-header">
					<div class="rma-view-title">
						<h2>${__("Recent RMA Cases")}</h2>
					</div>
					<button class="rma-btn-primary" id="rma-new-btn">+ ${__("New RMA Case")}</button>
				</div>
				<div class="rma-table-card" id="rma-recent-table">
					<div class="rma-empty">${__("Loading...")}</div>
				</div>
			</div>`);

		this.$content.find("#rma-new-btn").on("click", () => frappe.new_doc("RMA Case"));

		Promise.all([
			frappe.call({ method: `${RMA_API}.get_dashboard_stats`, args: { company } }),
			frappe.call({ method: `${RMA_API}.get_rma_cases`, args: { company, status_filter: "Open" } }),
		]).then(([stats_r, cases_r]) => {
			this.render_stats(stats_r.message || {});
			this.render_case_table(this.$content.find("#rma-recent-table"), cases_r.message || []);
		});
	}

	render_stats(data) {
		const cards = [
			{ label: "Open Cases", value: data.open_cases || 0, color: "#EA580C", filter: "Open" },
			{ label: "In Progress", value: data.in_progress || 0, color: "#D97706", filter: "In Progress" },
			{ label: "Pending Parts", value: data.pending_parts || 0, color: "#CA8A04", filter: "Pending Parts" },
			{ label: "Sent for Repair", value: data.sent_for_repair || 0, color: "#9333EA", filter: "Sent for Repair" },
			{ label: "Closed", value: data.closed || 0, color: "#059669", filter: "Closed" },
			{ label: "Total Cases", value: data.total || 0, color: "#2563EB", filter: "All" },
			{ label: "Under Warranty", value: data.under_warranty || 0, color: "#059669", action: "warranties-active" },
			{ label: "Expired Warranty", value: data.expired_warranty || 0, color: "#DC2626", action: "warranties-expired" },
		];

		const html = cards.map(c => `
			<div class="rma-stat-card" style="border-top: 3px solid ${c.color}"
				data-filter="${c.filter || ""}" data-action="${c.action || ""}">
				<div class="rma-stat-value" style="color:${c.color}">${c.value}</div>
				<div class="rma-stat-label">${__(c.label)}</div>
			</div>`).join("");

		this.$content.find("#rma-stats").html(html);

		const self = this;
		this.$content.find(".rma-stat-card").on("click", function () {
			const action = $(this).data("action");
			if (action === "warranties-active") {
				self.warranty_filter = "Under Warranty";
				self.switch_view("warranties");
			} else if (action === "warranties-expired") {
				self.warranty_filter = "Expired";
				self.switch_view("warranties");
			} else {
				self.case_filter = $(this).data("filter");
				self.switch_view("all-cases");
			}
		});
	}

	// ─── All Cases View ───

	refresh_all_cases() {
		const company = this.company || null;
		const filter = this.case_filter || "All";

		this.$content.html(`
			<div class="rma-view-header">
				<div class="rma-view-title">
					<h2>${__("RMA Case Register")}</h2>
					<p>${__("Return Merchandise Authorization \u2014 all active and closed cases")}</p>
				</div>
				<button class="rma-btn-primary" id="rma-new-btn2">+ ${__("New RMA Case")}</button>
			</div>
			<div class="rma-filter-row" id="rma-filters"></div>
			<div class="rma-table-card" id="rma-case-table">
				<div class="rma-empty">${__("Loading...")}</div>
			</div>`);

		this.$content.find("#rma-new-btn2").on("click", () => frappe.new_doc("RMA Case"));

		const filters = ["All", "Open", "In Progress", "Pending Parts", "Sent for Repair", "Repaired", "Replaced", "Closed"];
		const pills = filters.map(f =>
			`<span class="rma-filter-pill${f === filter ? " active" : ""}" data-filter="${f}">${__(f)}</span>`
		).join("");
		this.$content.find("#rma-filters").html(pills);

		this.$content.find(".rma-filter-pill").on("click", (e) => {
			this.case_filter = $(e.currentTarget).data("filter");
			this.refresh_all_cases();
		});

		frappe.call({
			method: `${RMA_API}.get_rma_cases`,
			args: { company, status_filter: filter },
		}).then(r => {
			this.render_case_table(this.$content.find("#rma-case-table"), r.message || []);
		});
	}

	// ─── Warranties View ───

	refresh_warranties() {
		const company = this.company || null;
		const filter = this.warranty_filter || "All";

		this.$content.html(`
			<div class="rma-view-header">
				<div class="rma-view-title">
					<h2>${__("Warranty Register")}</h2>
					<p>${__("Track warranty status for delivered items")}</p>
				</div>
			</div>
			<div class="rma-filter-row" id="wty-filters"></div>
			<div class="rma-table-card" id="wty-table">
				<div class="rma-empty">${__("Loading...")}</div>
			</div>`);

		const filters = ["All", "Under Warranty", "Expired", "Voided"];
		const pills = filters.map(f =>
			`<span class="rma-filter-pill${f === filter ? " active" : ""}" data-filter="${f}">${__(f)}</span>`
		).join("");
		this.$content.find("#wty-filters").html(pills);

		this.$content.find(".rma-filter-pill").on("click", (e) => {
			this.warranty_filter = $(e.currentTarget).data("filter");
			this.refresh_warranties();
		});

		frappe.call({
			method: `${RMA_API}.get_warranties`,
			args: { company, status_filter: filter },
		}).then(r => {
			this.render_warranty_table(this.$content.find("#wty-table"), r.message || []);
		});
	}

	render_warranty_table($container, data) {
		if (!data.length) {
			$container.html(`<div class="rma-empty">${__("No warranty records found")}</div>`);
			return;
		}

		const rows = data.map(r => {
			const status_cls = r.status === "Under Warranty" ? "rma-badge-warranty"
				: r.status === "Expired" ? "rma-badge-no-warranty"
				: "";
			const days = r.days_remaining || 0;
			const days_color = days > 90 ? "#059669" : days > 30 ? "#D97706" : "#DC2626";

			return `
			<tr style="cursor:pointer" onclick="frappe.set_route('Form','Warranty List','${r.name}')">
				<td><span class="rma-case-id">${r.name}</span></td>
				<td><span class="rma-badge ${status_cls}">${__(r.status).toUpperCase()}</span></td>
				<td style="font-weight:600">${r.customer_name || r.customer || "\u2014"}</td>
				<td>${r.item_code || "\u2014"}</td>
				<td style="color:var(--text-muted)">${r.item_name || "\u2014"}</td>
				<td style="color:var(--text-muted); font-size:0.82rem">${r.serial_no || "\u2014"}</td>
				<td style="color:var(--text-muted); font-size:0.82rem">${frappe.datetime.str_to_user(r.warranty_start_date) || "\u2014"}</td>
				<td style="color:var(--text-muted); font-size:0.82rem">${frappe.datetime.str_to_user(r.warranty_end_date) || "\u2014"}</td>
				<td style="font-weight:700; color:${days_color}">${r.status === "Under Warranty" ? days + " days" : "\u2014"}</td>
				<td><span class="rma-case-id" onclick="event.stopPropagation(); frappe.set_route('Form','Delivery Note','${r.delivery_note || ""}')">${r.delivery_note || "\u2014"}</span></td>
			</tr>`;
		}).join("");

		$container.html(`
			<div style="overflow-x:auto">
			<table class="rma-table">
				<thead><tr>
					<th>${__("ID")}</th>
					<th>${__("Status")}</th>
					<th>${__("Customer")}</th>
					<th>${__("Item Code")}</th>
					<th>${__("Item Name")}</th>
					<th>${__("Serial No")}</th>
					<th>${__("Start Date")}</th>
					<th>${__("End Date")}</th>
					<th>${__("Remaining")}</th>
					<th>${__("Delivery Note")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
			</div>`);
	}

	render_case_table($container, data) {
		if (!data.length) {
			$container.html(`<div class="rma-empty">${__("No RMA cases found")}</div>`);
			return;
		}

		const status_badge_map = {
			"Open": "rma-badge-open",
			"In Progress": "rma-badge-in-progress",
			"Pending Parts": "rma-badge-pending-parts",
			"Sent for Repair": "rma-badge-sent-for-repair",
			"Repaired": "rma-badge-repaired",
			"Replaced": "rma-badge-replaced",
			"Closed": "rma-badge-closed",
			"Cancelled": "rma-badge-cancelled",
		};

		const priority_badge_map = {
			"Critical": "rma-badge-critical",
			"High": "rma-badge-high",
			"Medium": "rma-badge-medium",
			"Low": "rma-badge-low",
		};

		const rows = data.map(r => {
			const badge_cls = status_badge_map[r.status] || "";
			const priority_cls = priority_badge_map[r.priority] || "";
			const warranty_cls = (r.warranty_status === "Under Warranty")
				? "rma-badge-warranty"
				: (r.warranty_status === "Out of Warranty" || r.warranty_status === "Expired")
					? "rma-badge-no-warranty" : "";

			const standby_html = r.standby_unit
				? `<span class="rma-case-id" onclick="event.stopPropagation(); frappe.set_route('Form','Asset','${r.standby_unit}')">${r.standby_unit}</span>`
				: `<span style="color:var(--text-muted)">\u2014</span>`;

			return `
			<tr style="cursor:pointer" onclick="frappe.set_route('Form','RMA Case','${r.name}')">
				<td><span class="rma-case-id">${r.name}</span></td>
				<td><span class="rma-badge ${badge_cls}">${__(r.status).toUpperCase()}</span></td>
				<td><span class="rma-badge ${priority_cls}">${__(r.priority || "Medium")}</span></td>
				<td style="font-weight:600">${r.customer || "\u2014"}</td>
				<td style="color:var(--text-muted); font-size:0.82rem">${r.item_description || "\u2014"}</td>
				<td style="color:var(--text-muted); font-size:0.78rem; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap"
					title="${frappe.utils.escape_html(r.fault_description || "")}">${r.fault_description || "\u2014"}</td>
				<td>${r.warranty_status ? `<span class="rma-badge ${warranty_cls}">${__(r.warranty_status).toUpperCase()}</span>` : "\u2014"}</td>
				<td>${standby_html}</td>
				<td style="color:var(--text-muted); font-size:0.82rem">${r.requested_salesperson || "\u2014"}</td>
				<td style="color:var(--text-muted); font-size:0.82rem">${frappe.datetime.str_to_user(r.rma_date) || "\u2014"}</td>
			</tr>`;
		}).join("");

		$container.html(`
			<div style="overflow-x:auto">
			<table class="rma-table">
				<thead><tr>
					<th>${__("Case ID")}</th>
					<th>${__("Status")}</th>
					<th>${__("Priority")}</th>
					<th>${__("Customer")}</th>
					<th>${__("Product")}</th>
					<th>${__("Issue")}</th>
					<th>${__("Warranty")}</th>
					<th>${__("Standby Unit")}</th>
					<th>${__("Salesperson")}</th>
					<th>${__("Date")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
			</div>`);
	}
}
