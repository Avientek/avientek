frappe.pages["sales-team-dashboard"].on_page_load = function (wrapper) {
    frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Sales Team Dashboard"),
        single_column: true,
    });

    wrapper.dashboard = new SalesTeamDashboard(wrapper);
    frappe.breadcrumbs.add("Selling");
};

class SalesTeamDashboard {
    constructor(wrapper) {
        this.page = wrapper.page;
        this.parent = $(wrapper).find(".layout-main-section");
        this.active_card = null;
        this.data = null;

        setTimeout(() => {
            this.setup_filters();
            this.setup_containers();
            this.refresh();
        }, 0);
    }

    setup_filters() {
        this.company_field = this.page.add_field({
            fieldtype: "Link",
            fieldname: "company",
            options: "Company",
            label: __("Company"),
            default: frappe.defaults.get_user_default("company"),
            change: () => this.refresh(),
        });

        this.from_date_field = this.page.add_field({
            fieldtype: "Date",
            fieldname: "from_date",
            label: __("From Date"),
            default: frappe.datetime.add_months(frappe.datetime.get_today(), -12),
            change: () => this.refresh(),
        });

        this.to_date_field = this.page.add_field({
            fieldtype: "Date",
            fieldname: "to_date",
            label: __("To Date"),
            default: frappe.datetime.get_today(),
            change: () => this.refresh(),
        });

        this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
    }

    setup_containers() {
        this.cards_container = $('<div class="std-cards-container"></div>').appendTo(this.parent);
        this.detail_container = $('<div class="std-detail-container" style="display:none;"></div>')
            .appendTo(this.parent);
    }

    get_filters() {
        return {
            company: this.company_field ? this.company_field.get_value() : "",
            from_date: this.from_date_field ? this.from_date_field.get_value() : "",
            to_date: this.to_date_field ? this.to_date_field.get_value() : "",
        };
    }

    refresh() {
        let filters = this.get_filters();
        frappe.call({
            method: "avientek.avientek.page.sales_team_dashboard.sales_team_dashboard.get_dashboard_data",
            args: filters,
            callback: (r) => {
                if (!r.exc) {
                    this.data = r.message;
                    this.render_cards();
                    if (this.active_card) {
                        this.show_detail(this.active_card);
                    } else {
                        this.detail_container.hide();
                    }
                }
            },
        });
    }

    render_cards() {
        let d = this.data;
        let currency = d.currency;
        this.cards_container.empty();

        let cards = [
            {
                key: "total_so",
                title: __("Total Sales Orders"),
                count: d.summary.total_count,
                value: format_currency(d.summary.total_value, currency),
                color: "#4C9AFF",
                icon: "file",
            },
            {
                key: "open_so",
                title: __("Open Sales Orders"),
                count: d.summary.open_count,
                value: format_currency(d.summary.open_value, currency),
                color: "#FF8B00",
                icon: "clock",
            },
            {
                key: "invoices",
                title: __("Invoices (Open SOs)"),
                count: d.summary.invoice_count,
                value: format_currency(d.summary.invoice_value, currency),
                color: "#36B37E",
                icon: "income",
            },
        ];

        let row = $('<div class="std-cards-row"></div>').appendTo(this.cards_container);

        cards.forEach((card) => {
            let active_cls = this.active_card === card.key ? "active" : "";
            let $card = $(`
                <div class="std-summary-card ${active_cls}" data-card="${card.key}">
                    <div class="card-color-bar" style="background:${card.color};"></div>
                    <div class="card-body-inner">
                        <div class="card-title">${card.title}</div>
                        <div class="card-count">${card.count}</div>
                        <div class="card-value">${card.value}</div>
                        <div class="card-hint text-muted">${__("Click for details")}</div>
                    </div>
                </div>
            `).appendTo(row);

            $card.on("click", () => {
                if (this.active_card === card.key) {
                    this.active_card = null;
                    this.detail_container.slideUp(200);
                    row.find(".std-summary-card").removeClass("active");
                } else {
                    this.active_card = card.key;
                    row.find(".std-summary-card").removeClass("active");
                    $card.addClass("active");
                    this.show_detail(card.key);
                }
            });
        });
    }

    show_detail(card_key) {
        let d = this.data;
        this.detail_container.empty().slideDown(200);

        let title_map = {
            total_so: __("All Sales Orders"),
            open_so: __("Open Sales Orders"),
            invoices: __("Invoices for Open Sales Orders"),
        };

        let wrapper = $(`
            <div class="detail-header">
                <h5>${title_map[card_key] || ""}</h5>
            </div>
            <div class="detail-tables-wrapper">
                <div class="detail-section customer-section">
                    <h6>${__("Customer-wise Breakdown")}</h6>
                    <div class="customer-table"></div>
                </div>
                <div class="detail-section brand-section">
                    <h6>${__("Brand-wise Breakdown")}</h6>
                    <div class="brand-table"></div>
                </div>
            </div>
        `).appendTo(this.detail_container);

        // Customer table
        this.render_detail_table(
            wrapper.find(".customer-table"),
            [__("Customer"), __("Orders"), __("Value")],
            d.customer_data.map((r) => ({
                cells: [
                    `<a href="/app/sales-order?customer=${encodeURIComponent(r.customer)}&status=["in",["To Deliver and Bill","To Deliver","To Bill"]]">${r.customer_name || r.customer}</a>`,
                    r.count,
                    format_currency(r.value, d.currency),
                ],
            }))
        );

        // Brand table
        this.render_detail_table(
            wrapper.find(".brand-table"),
            [__("Brand"), __("SO Count"), __("Value")],
            d.brand_data.map((r) => ({
                cells: [
                    r.brand,
                    r.so_count,
                    format_currency(r.value, d.currency),
                ],
            }))
        );
    }

    render_detail_table($container, headers, rows) {
        if (!rows.length) {
            $container.html(`<p class="text-muted">${__("No data")}</p>`);
            return;
        }

        let table = $('<table class="table table-bordered table-sm std-detail-table"></table>');
        let thead = $("<thead></thead>").appendTo(table);
        let tr = $("<tr></tr>").appendTo(thead);
        headers.forEach((h, i) => {
            let align = i >= 1 ? ' class="text-right"' : "";
            tr.append(`<th${align}>${h}</th>`);
        });

        let tbody = $("<tbody></tbody>").appendTo(table);
        rows.forEach((row) => {
            let r = $("<tr></tr>").appendTo(tbody);
            row.cells.forEach((cell, i) => {
                let align = i >= 1 ? ' class="text-right"' : "";
                r.append(`<td${align}>${cell}</td>`);
            });
        });

        $container.append(table);
    }
}
