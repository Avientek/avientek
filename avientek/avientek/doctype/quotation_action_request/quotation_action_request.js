frappe.ui.form.on("Quotation Action Request", {
    refresh(frm) {
        // Quick link to the underlying Quotation for reviewers.
        if (frm.doc.quotation) {
            frm.add_custom_button(
                __("Open Quotation"),
                () => frappe.set_route("Form", "Quotation", frm.doc.quotation),
                __("View"),
            );
        }
        if (frm.doc.amended_quotation) {
            frm.add_custom_button(
                __("Open Amended Quotation"),
                () => frappe.set_route(
                    "Form", "Quotation", frm.doc.amended_quotation,
                ),
                __("View"),
            );
        }
    },
    quotation(frm) {
        if (!frm.doc.quotation) return;
        frappe.db.get_value(
            "Quotation", frm.doc.quotation,
            ["probability", "workflow_state"],
        ).then(r => {
            const v = r.message || {};
            frm.set_value("current_probability", v.probability);
            frm.set_value("current_workflow_state", v.workflow_state);
        });
    },
});
