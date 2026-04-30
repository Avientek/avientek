// Copyright (c) 2026, Avientek and contributors
// For license information, please see license.txt

frappe.query_reports["Sales Person Target vs Actual"] = {
    filters: [
        {
            fieldname: "fiscal_year",
            label: __("Fiscal Year"),
            fieldtype: "Link",
            options: "Fiscal Year",
            default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today()),
            reqd: 1,
        },
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            description: __("Optional. Scopes Sales Order / Sales Invoice actuals to one company. Leave empty for cross-company totals."),
        },
        {
            fieldname: "sales_person",
            label: __("Sales Person"),
            fieldtype: "Link",
            options: "Sales Person",
        },
        {
            fieldname: "currency",
            label: __("Reporting Currency"),
            fieldtype: "Link",
            options: "Currency",
            default: "USD",
            description: __("Targets and actuals are converted to this currency at posting-date FX rate."),
        },
    ],
    tree: true,
    name_field: "name",
    parent_field: "parent_target",
    initial_depth: 1,
    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);

        // Bold the Sales Person header rows
        if (data && data.indent === 0 && column.fieldname === "period") {
            value = `<b>${value}</b>`;
        }

        // Color-code variance + % columns: red if under target, green if at/above
        if (data && column.fieldname && (
            column.fieldname.endsWith("_variance") || column.fieldname.endsWith("_pct")
        )) {
            const raw = data[column.fieldname];
            if (raw !== undefined && raw !== null) {
                const target_field = column.fieldname.endsWith("_variance")
                    ? "target_" + column.fieldname.replace("_variance", "")
                    : "target_" + column.fieldname.replace("_pct", "");
                if (data[target_field] && data[target_field] > 0) {
                    const is_pct = column.fieldname.endsWith("_pct");
                    const ok = is_pct ? (raw >= 100) : (raw >= 0);
                    value = `<span style="color:${ok ? '#198754' : '#dc3545'}; font-weight:600;">${value}</span>`;
                }
            }
        }
        return value;
    },
};
