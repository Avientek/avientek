frappe.ui.form.on("Employee Activity Log", {

	refresh(frm) {
		frm.trigger("set_status_indicator");
		frm.trigger("add_action_buttons");
	},

	check_in_time(frm) { frm.trigger("calc_duration"); },
	check_out_time(frm) { frm.trigger("calc_duration"); },

	calc_duration(frm) {
		const cin = frm.doc.check_in_time;
		const cout = frm.doc.check_out_time;
		if (cin && cout) {
			const [ih, im] = cin.split(":").map(Number);
			const [oh, om] = cout.split(":").map(Number);
			const diff = ((oh * 60 + om) - (ih * 60 + im)) / 60;
			frm.set_value("duration_hours", diff > 0 ? Math.round(diff * 100) / 100 : 0);
		}
	},

	set_status_indicator(frm) {
		const color_map = {
			"Planned": "gray",
			"In Progress": "blue",
			"Completed": "green",
			"Cancelled": "red",
		};
		const approval_color = {
			"Pending": "orange",
			"Approved": "green",
			"Rejected": "red",
		};
		frm.page.set_indicator(frm.doc.status, color_map[frm.doc.status] || "gray");
	},

	add_action_buttons(frm) {
		if (frm.is_new()) return;

		const is_manager = frappe.user.has_role(["Sales Manager", "System Manager", "HR Manager"]);

		// Approve / Reject — managers only, on submitted docs with Pending approval
		if (is_manager && frm.doc.docstatus === 1 && frm.doc.approval_status === "Pending") {
			frm.add_custom_button(__("Approve"), () => {
				frappe.confirm(__("Approve this activity log?"), () => {
					frappe.call({
						method: "avientek.avientek.doctype.employee_activity_log.employee_activity_log.EmployeeActivityLog.approve",
						doc: frm.doc,
					}).then(() => frm.reload_doc());
				});
			}, __("Actions"));

			frm.add_custom_button(__("Reject"), () => {
				frappe.prompt({
					fieldname: "comments",
					fieldtype: "Small Text",
					label: __("Rejection Comments"),
				}, (val) => {
					frappe.call({
						method: "avientek.avientek.doctype.employee_activity_log.employee_activity_log.EmployeeActivityLog.reject",
						doc: frm.doc,
						args: { comments: val.comments },
					}).then(() => frm.reload_doc());
				}, __("Reject Activity Log"), __("Reject"));
			}, __("Actions"));
		}

		// Quick links
		if (frm.doc.customer) {
			frm.add_custom_button(__("Customer Logs"), () => {
				frappe.set_route("List", "Employee Activity Log", { customer: frm.doc.customer });
			}, __("View"));
		}
		if (frm.doc.employee) {
			frm.add_custom_button(__("My Activities"), () => {
				frappe.set_route("List", "Employee Activity Log", { employee: frm.doc.employee });
			}, __("View"));
		}
	},
});
