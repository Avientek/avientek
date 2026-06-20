frappe.ui.form.on("PRF Approval Rule", {
    refresh(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("Test against a PRF"), () => {
                frappe.prompt(
                    [
                        {
                            label: __("Payment Request Form"),
                            fieldname: "prf",
                            fieldtype: "Link",
                            options: "Payment Request Form",
                            reqd: 1,
                        },
                    ],
                    (values) => {
                        frappe.call({
                            method: "avientek.events.payment_request_form.preview_resolved_chain",
                            args: { prf_name: values.prf },
                            callback: (r) => {
                                if (r.message) {
                                    frappe.msgprint({
                                        title: __("Resolved Chain"),
                                        message: `<pre>${JSON.stringify(r.message, null, 2)}</pre>`,
                                        indicator: "blue",
                                    });
                                }
                            },
                        });
                    },
                    __("Preview resolved approval chain"),
                    __("Resolve"),
                );
            });
        }
    },
});
