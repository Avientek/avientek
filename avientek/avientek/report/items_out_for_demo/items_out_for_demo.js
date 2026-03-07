frappe.query_reports["Items Out for Demo"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_default("company"),
			reqd: 0,
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "All\nOpen\nOverdue",
			default: "All",
		},
		{
			fieldname: "salesperson",
			label: __("Salesperson"),
			fieldtype: "Link",
			options: "Sales Person",
		},
		{
			fieldname: "from_date",
			label: __("Move Out From"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("Move Out To"),
			fieldtype: "Date",
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (data && data.days_overdue > 0) {
			// Highlight entire overdue row in red
			if (column.fieldname === "status") {
				value = `<span class="indicator-pill red">${data.status}</span>`;
			} else if (column.fieldname === "days_overdue") {
				value = `<b style="color: var(--red-500)">${data.days_overdue}</b>`;
			} else if (column.fieldname === "expected_return_date") {
				value = `<span style="color: var(--red-500); font-weight:600">${value}</span>`;
			}
		} else if (data && data.status === "Open") {
			if (column.fieldname === "status") {
				value = `<span class="indicator-pill orange">${data.status}</span>`;
			}
		}

		return value;
	},
};
