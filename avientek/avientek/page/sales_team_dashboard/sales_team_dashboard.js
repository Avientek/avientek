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

        this.customer_field = this.page.add_field({
            fieldtype: "Link",
            fieldname: "customer",
            options: "Customer",
            label: __("Customer"),
            change: () => this.refresh(),
        });

        this.brand_field = this.page.add_field({
            fieldtype: "Link",
            fieldname: "brand",
            options: "Brand",
            label: __("Brand"),
            change: () => this.refresh(),
        });

        this.sales_person_field = this.page.add_field({
            fieldtype: "Link",
            fieldname: "sales_person",
            options: "Sales Person",
            label: __("Sales Person"),
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
            customer: this.customer_field ? this.customer_field.get_value() : "",
            brand: this.brand_field ? this.brand_field.get_value() : "",
            sales_person: this.sales_person_field ? this.sales_person_field.get_value() : "",
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
                    `<a href="#" class="customer-invoice-link" data-customer="${frappe.utils.escape_html(r.customer)}" data-customer-name="${frappe.utils.escape_html(r.customer_name || r.customer)}">${r.customer_name || r.customer}</a>`,
                    r.count,
                    format_currency(r.value, d.currency),
                ],
            }))
        );

        // Bind click on customer names to show invoice dialog
        wrapper.find(".customer-invoice-link").on("click", (e) => {
            e.preventDefault();
            let customer = $(e.currentTarget).data("customer");
            let customer_name = $(e.currentTarget).data("customer-name");
            this.show_customer_invoices(customer, customer_name);
        });

        // Brand table
        this.render_detail_table(
            wrapper.find(".brand-table"),
            [__("Brand"), __("SO Count"), __("Value")],
            d.brand_data.map((r) => ({
                cells: [
                    `<a href="#" class="brand-detail-link" data-brand="${frappe.utils.escape_html(r.brand)}">${r.brand}</a>`,
                    r.so_count,
                    format_currency(r.value, d.currency),
                ],
            }))
        );

        // Bind click on brand names to show orders dialog
        wrapper.find(".brand-detail-link").on("click", (e) => {
            e.preventDefault();
            let brand = $(e.currentTarget).data("brand");
            this.show_brand_orders(brand);
        });
    }

    show_customer_invoices(customer, customer_name) {
        let filters = this.get_filters();
        frappe.call({
            method: "avientek.avientek.page.sales_team_dashboard.sales_team_dashboard.get_customer_orders",
            args: {
                customer: customer,
                company: filters.company,
                from_date: filters.from_date,
                to_date: filters.to_date,
                brand: filters.brand,
                sales_person: filters.sales_person,
            },
            callback: (r) => {
                if (r.exc) return;
                let data = r.message;
                let currency = data.currency;
                let orders = data.orders || [];
                let invoices = data.invoices || [];

                // --- Sales Orders table ---
                let so_rows = "";
                if (!orders.length) {
                    so_rows = `<tr><td colspan="5" class="text-muted text-center">${__("No orders found")}</td></tr>`;
                } else {
                    orders.forEach((so) => {
                        so_rows += `
                            <tr>
                                <td><a href="#" class="doc-preview-link" data-doctype="Sales Order" data-name="${so.name}">${so.name}</a></td>
                                <td>${frappe.datetime.str_to_user(so.transaction_date)}</td>
                                <td>${so.status}</td>
                                <td class="text-right">${format_currency(so.base_grand_total, currency)}</td>
                                <td class="text-right">${flt(so.per_billed, 1)}%</td>
                            </tr>`;
                    });
                }
                let so_total = orders.reduce((s, so) => s + flt(so.base_grand_total), 0);

                // --- Invoices table ---
                let si_rows = "";
                if (!invoices.length) {
                    si_rows = `<tr><td colspan="5" class="text-muted text-center">${__("No invoices found")}</td></tr>`;
                } else {
                    invoices.forEach((inv) => {
                        si_rows += `
                            <tr>
                                <td><a href="#" class="doc-preview-link" data-doctype="Sales Invoice" data-name="${inv.name}">${inv.name}</a></td>
                                <td>${frappe.datetime.str_to_user(inv.posting_date)}</td>
                                <td>${inv.status}</td>
                                <td class="text-right">${format_currency(inv.base_grand_total, currency)}</td>
                                <td class="text-right">${format_currency(inv.outstanding_amount, currency)}</td>
                            </tr>`;
                    });
                }
                let si_total = invoices.reduce((s, inv) => s + flt(inv.base_grand_total), 0);
                let si_outstanding = invoices.reduce((s, inv) => s + flt(inv.outstanding_amount), 0);

                let list_html = `
                    <h6 style="margin-bottom:10px;">${__("Open Sales Orders")} (${orders.length})</h6>
                    <table class="table table-bordered table-sm std-detail-table" style="margin-bottom:24px;">
                        <thead>
                            <tr>
                                <th>${__("Sales Order")}</th>
                                <th>${__("Date")}</th>
                                <th>${__("Status")}</th>
                                <th class="text-right">${__("Amount")}</th>
                                <th class="text-right">${__("% Billed")}</th>
                            </tr>
                        </thead>
                        <tbody>${so_rows}</tbody>
                        ${orders.length ? `<tfoot>
                            <tr style="font-weight:700;">
                                <td colspan="3">${__("Total")}</td>
                                <td class="text-right">${format_currency(so_total, currency)}</td>
                                <td></td>
                            </tr>
                        </tfoot>` : ""}
                    </table>

                    <h6 style="margin-bottom:10px;">${__("Invoices")} (${invoices.length})</h6>
                    <table class="table table-bordered table-sm std-detail-table">
                        <thead>
                            <tr>
                                <th>${__("Invoice")}</th>
                                <th>${__("Date")}</th>
                                <th>${__("Status")}</th>
                                <th class="text-right">${__("Amount")}</th>
                                <th class="text-right">${__("Outstanding")}</th>
                            </tr>
                        </thead>
                        <tbody>${si_rows}</tbody>
                        ${invoices.length ? `<tfoot>
                            <tr style="font-weight:700;">
                                <td colspan="3">${__("Total")}</td>
                                <td class="text-right">${format_currency(si_total, currency)}</td>
                                <td class="text-right">${format_currency(si_outstanding, currency)}</td>
                            </tr>
                        </tfoot>` : ""}
                    </table>`;

                let dialog_title = __("{0}", [customer_name]);
                let dialog = new frappe.ui.Dialog({
                    title: dialog_title,
                    size: "extra-large",
                    fields: [
                        { fieldtype: "HTML", fieldname: "content", options: list_html },
                    ],
                });
                dialog.show();

                // Bind doc preview links inside dialog
                dialog.$wrapper.on("click", ".doc-preview-link", (e) => {
                    e.preventDefault();
                    let doctype = $(e.currentTarget).data("doctype");
                    let name = $(e.currentTarget).data("name");
                    this.show_doc_in_dialog(dialog, doctype, name, dialog_title, list_html);
                });
            },
        });
    }

    show_brand_orders(brand) {
        let filters = this.get_filters();
        frappe.call({
            method: "avientek.avientek.page.sales_team_dashboard.sales_team_dashboard.get_brand_orders",
            args: {
                brand: brand,
                company: filters.company,
                from_date: filters.from_date,
                to_date: filters.to_date,
                customer: filters.customer,
                sales_person: filters.sales_person,
            },
            callback: (r) => {
                if (r.exc) return;
                let data = r.message;
                let currency = data.currency;
                let orders = data.orders || [];
                let invoices = data.invoices || [];

                // --- Sales Orders table ---
                let so_rows = "";
                if (!orders.length) {
                    so_rows = `<tr><td colspan="6" class="text-muted text-center">${__("No orders found")}</td></tr>`;
                } else {
                    orders.forEach((so) => {
                        so_rows += `
                            <tr>
                                <td><a href="#" class="doc-preview-link" data-doctype="Sales Order" data-name="${so.name}">${so.name}</a></td>
                                <td>${so.customer_name || ""}</td>
                                <td>${frappe.datetime.str_to_user(so.transaction_date)}</td>
                                <td>${so.status}</td>
                                <td class="text-right">${format_currency(so.brand_amount, currency)}</td>
                                <td class="text-right">${flt(so.per_billed, 1)}%</td>
                            </tr>`;
                    });
                }
                let so_total = orders.reduce((s, so) => s + flt(so.brand_amount), 0);

                // --- Invoices table ---
                let si_rows = "";
                if (!invoices.length) {
                    si_rows = `<tr><td colspan="4" class="text-muted text-center">${__("No invoices found")}</td></tr>`;
                } else {
                    invoices.forEach((inv) => {
                        si_rows += `
                            <tr>
                                <td><a href="#" class="doc-preview-link" data-doctype="Sales Invoice" data-name="${inv.name}">${inv.name}</a></td>
                                <td>${frappe.datetime.str_to_user(inv.posting_date)}</td>
                                <td>${inv.status}</td>
                                <td class="text-right">${format_currency(inv.brand_amount, currency)}</td>
                            </tr>`;
                    });
                }
                let si_total = invoices.reduce((s, inv) => s + flt(inv.brand_amount), 0);

                let dialog_title = __("Brand: {0}", [brand]);
                let list_html = `
                    <h6 style="margin-bottom:10px;">${__("Open Sales Orders")} (${orders.length})</h6>
                    <table class="table table-bordered table-sm std-detail-table" style="margin-bottom:24px;">
                        <thead>
                            <tr>
                                <th>${__("Sales Order")}</th>
                                <th>${__("Customer")}</th>
                                <th>${__("Date")}</th>
                                <th>${__("Status")}</th>
                                <th class="text-right">${__("Brand Amount")}</th>
                                <th class="text-right">${__("% Billed")}</th>
                            </tr>
                        </thead>
                        <tbody>${so_rows}</tbody>
                        ${orders.length ? `<tfoot>
                            <tr style="font-weight:700;">
                                <td colspan="4">${__("Total")}</td>
                                <td class="text-right">${format_currency(so_total, currency)}</td>
                                <td></td>
                            </tr>
                        </tfoot>` : ""}
                    </table>

                    <h6 style="margin-bottom:10px;">${__("Invoices")} (${invoices.length})</h6>
                    <table class="table table-bordered table-sm std-detail-table">
                        <thead>
                            <tr>
                                <th>${__("Invoice")}</th>
                                <th>${__("Date")}</th>
                                <th>${__("Status")}</th>
                                <th class="text-right">${__("Brand Amount")}</th>
                            </tr>
                        </thead>
                        <tbody>${si_rows}</tbody>
                        ${invoices.length ? `<tfoot>
                            <tr style="font-weight:700;">
                                <td colspan="3">${__("Total")}</td>
                                <td class="text-right">${format_currency(si_total, currency)}</td>
                            </tr>
                        </tfoot>` : ""}
                    </table>`;

                let dialog = new frappe.ui.Dialog({
                    title: dialog_title,
                    size: "extra-large",
                    fields: [
                        { fieldtype: "HTML", fieldname: "content", options: list_html },
                    ],
                });
                dialog.show();

                // Bind doc preview links inside dialog
                dialog.$wrapper.on("click", ".doc-preview-link", (e) => {
                    e.preventDefault();
                    let doctype = $(e.currentTarget).data("doctype");
                    let name = $(e.currentTarget).data("name");
                    this.show_doc_in_dialog(dialog, doctype, name, dialog_title, list_html);
                });
            },
        });
    }

    show_doc_in_dialog(dialog, doctype, name, dialog_title, list_html) {
        frappe.call({
            method: "frappe.client.get",
            args: { doctype: doctype, name: name },
            callback: (r) => {
                if (r.exc) return;
                let doc = r.message;
                let currency = this.data?.currency || doc.currency || "";
                let slug = doctype.toLowerCase().replace(/ /g, "-");

                // Build items table
                let items_html = "";
                let items = doc.items || [];
                if (items.length) {
                    let item_rows = items.map((item) => `
                        <tr>
                            <td>${item.item_code}</td>
                            <td>${item.item_name || ""}</td>
                            <td class="text-right">${flt(item.qty, 2)}</td>
                            <td class="text-right">${format_currency(item.rate, currency)}</td>
                            <td class="text-right">${format_currency(item.amount, currency)}</td>
                        </tr>`).join("");
                    items_html = `
                        <h6 style="margin:16px 0 8px;">${__("Items")}</h6>
                        <table class="table table-bordered table-sm std-detail-table">
                            <thead><tr>
                                <th>${__("Item Code")}</th>
                                <th>${__("Item Name")}</th>
                                <th class="text-right">${__("Qty")}</th>
                                <th class="text-right">${__("Rate")}</th>
                                <th class="text-right">${__("Amount")}</th>
                            </tr></thead>
                            <tbody>${item_rows}</tbody>
                        </table>`;
                }

                // Build header info
                let date_label = doctype === "Sales Order" ? __("Order Date") : __("Posting Date");
                let date_val = doc.transaction_date || doc.posting_date || "";
                let header_html = `
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                        <button class="btn btn-sm btn-default back-to-list">
                            ← ${__("Back")}
                        </button>
                        <a href="/app/${slug}/${name}" class="btn btn-sm btn-primary" target="_blank">
                            ${__("Open Full Form")} ↗
                        </a>
                    </div>
                    <table class="table table-sm" style="margin-bottom:0;">
                        <tbody>
                            <tr><td style="width:140px;font-weight:600;">${date_label}</td><td>${date_val ? frappe.datetime.str_to_user(date_val) : ""}</td></tr>
                            <tr><td style="font-weight:600;">${__("Customer")}</td><td>${doc.customer_name || doc.customer || ""}</td></tr>
                            <tr><td style="font-weight:600;">${__("Status")}</td><td>${doc.status || ""}</td></tr>
                            <tr><td style="font-weight:600;">${__("Grand Total")}</td><td>${format_currency(doc.base_grand_total, currency)}</td></tr>
                            ${doc.outstanding_amount != null ? `<tr><td style="font-weight:600;">${__("Outstanding")}</td><td>${format_currency(doc.outstanding_amount, currency)}</td></tr>` : ""}
                        </tbody>
                    </table>`;

                // Replace dialog content
                dialog.set_title(`${doctype}: ${name}`);
                dialog.fields_dict.content.$wrapper.html(header_html + items_html);

                // Back button returns to list view
                dialog.$wrapper.find(".back-to-list").on("click", () => {
                    dialog.set_title(dialog_title);
                    dialog.fields_dict.content.$wrapper.html(list_html);
                });
            },
        });
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
