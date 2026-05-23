// Copyright (c) 2026, Avientek and contributors
// For license information, please see license.txt

frappe.query_reports["Payment Request Form Summary"] = {
    filters: [
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.add_days(frappe.datetime.get_today(), -90),
            reqd: 0,
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today(),
            reqd: 0,
        },
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
        },
        {
            fieldname: "payment_type",
            label: __("Payment Type"),
            fieldtype: "Select",
            options: ["", "Pay", "Internal Transfer", "Advance Pay"].join("\n"),
        },
        {
            fieldname: "workflow_state",
            label: __("Status"),
            fieldtype: "Select",
            options: [
                "",
                "Draft",
                "Authorised",
                "Approved Level 1",
                "Approved Level 2",
                "Released",
                "Pending L2 Approval",
                "Cancellation L2 Pending",
                "Cancelled",
                "Rejected",
            ].join("\n"),
        },
        {
            fieldname: "party_type",
            label: __("Party Type"),
            fieldtype: "Link",
            options: "DocType",
            get_query: function () {
                return { filters: { name: ["in", ["Supplier", "Customer", "Employee"]] } };
            },
        },
        {
            fieldname: "party",
            label: __("Party"),
            fieldtype: "Dynamic Link",
            get_options: function () {
                return frappe.query_report.get_filter_value("party_type") || "";
            },
        },
        {
            fieldname: "department",
            label: __("Department"),
            fieldtype: "Link",
            options: "Department",
        },
        // Jithin 2026-05-23: the Show Base Currency Amount checkbox
        // was removed — the PRF-Amount Company Currency column is now
        // always visible per his Excel template.
    ],
};
