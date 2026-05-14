// Copyright (c) 2026, Avientek and contributors
// For license information, please see license.txt
//
// Adds a Menu shortcut on the PRF list view that opens the
// consolidated "Payment Request Form Summary" script report —
// a single Net Amount + Currency pair regardless of payment_type.

frappe.listview_settings["Payment Request Form"] = {
    onload: function (listview) {
        listview.page.add_menu_item(__("Summary Report"), function () {
            frappe.set_route("query-report", "Payment Request Form Summary");
        });
    },
};
