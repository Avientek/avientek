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
        {
            fieldname: "_note_margin",
            label: "",
            fieldtype: "HTML",
            options: '<div class="text-muted small" style="margin-top:6px;">' +
                __("Margin actual = Sales Invoice grand_total − cost-of-goods (Stock Ledger Entry sum). For SIs that flow from Delivery Note (update_stock=0), the SLE lives on the DN, not the SI — those SIs report margin ≈ billing. v2 will walk the DN chain.") +
                '</div>',
        },
    ],
    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);

        // Color-code variance + % columns: red for under target, green for at/above
        if (data && column.fieldname && (
            column.fieldname.endsWith("_variance") || column.fieldname.endsWith("_pct")
        )) {
            const raw = data[column.fieldname];
            if (raw !== undefined && raw !== null) {
                const target_field = column.fieldname.replace("_variance", "").replace("_pct", "")
                    .replace("booking", "target_booking").replace("billing", "target_billing").replace("margin", "target_margin");
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
