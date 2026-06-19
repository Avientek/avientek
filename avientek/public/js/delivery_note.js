// ── Client Script: "Delivery Note" ──
//
// Avientek customizations on Delivery Note:
//   1. Company → filtered Customer query (sales-team access control)
//   2. After save: auto-share to sales-team users (existing flow)
//   3. Void Draft workflow (Jithin 2026-06-19): a "Void this Draft"
//      button on Draft DNs. Server hook at
//      avientek.events.delivery_note.validate_void_state enforces the
//      one-way + locked + can't-submit invariants. UI side: red
//      indicator + button + reason prompt.
frappe.ui.form.on('Delivery Note', {
    refresh: function(frm) {
        // ── Void indicator (red) when the DN is voided ──
        // Frappe's status indicator only knows about docstatus; we
        // visually upgrade voided Drafts to look Cancelled.
        if (frm.doc.custom_is_void) {
            frm.page.set_indicator(__("Cancelled (Voided Draft)"), "red");
        }

        // ── "Void this Draft" button — only on Draft (docstatus=0)
        //    AND not already voided. Hidden on Submitted / Cancelled.
        if (frm.doc.docstatus === 0 && !frm.doc.custom_is_void && !frm.is_new()) {
            frm.add_custom_button(__("Void this Draft"), function() {
                frappe.prompt(
                    [{
                        label: __("Reason"),
                        fieldname: "reason",
                        fieldtype: "Small Text",
                        reqd: 1,
                    }],
                    function(values) {
                        frm.set_value("custom_void_reason", values.reason);
                        frm.set_value("custom_is_void", 1);
                        frm.save().then(() => {
                            frappe.show_alert({
                                message: __("Delivery Note voided. The DN remains in the system with its original number for audit; it will no longer appear in active Draft lists by default."),
                                indicator: "orange",
                            }, 7);
                        });
                    },
                    __("Void this Draft Delivery Note"),
                    __("Void"),
                );
            }, __("Actions"));
        }

        // ── Belt-and-suspenders: if voided, server-side hook already
        //    blocks edits, but we also visually disable the form so
        //    users don't get confused.
        if (frm.doc.custom_is_void) {
            frm.disable_save();
            // Disable all standard top-level fields (the void section
            // stays visible for audit reference). Skip "items" — the
            // child grid has its own locking mechanism below.
            ["customer", "set_warehouse", "taxes_and_charges",
             "shipping_rule", "tc_name"].forEach((fn) => {
                if (frm.fields_dict[fn]) {
                    frm.set_df_property(fn, "read_only", 1);
                }
            });
            // Lock items grid against row add/delete — no toggle_enable
            // here since that targets a field WITHIN a row, not the
            // grid itself (was throwing "field items not found").
            if (frm.fields_dict.items && frm.fields_dict.items.grid) {
                frm.fields_dict.items.grid.cannot_add_rows = true;
                frm.fields_dict.items.grid.cannot_delete_rows = true;
                frm.fields_dict.items.df.read_only = 1;
            }
        }
    },

    company: function(frm) {
        frappe.call({
            "method": "avientek.api.filtered_parties.get_filtered_customers",
            "args": {
                'company': frm.doc.company
            },
            callback: function(r) {
                if (r.message) {
                    frm.set_query("customer", function() {
                        return {
                            "filters": {
                                'name': ['in', r.message]
                            }
                        };
                    });
                }
            }
        });
    },
    setup: function(frm) {
        if (frm.doc.company) {
            frappe.call({
                "method": "avientek.api.filtered_parties.get_filtered_customers",
                "args": {
                    'company': frm.doc.company
                },
                callback: function(r) {
                    if (r.message) {
                        frm.set_query("customer", function() {
                            return {
                                "filters": {
                                    'name': ['in', r.message]
                                }
                            };
                        });
                    }
                }
            });
        }
    },
    after_save: async function(frm) {
        if (!frm.doc.sales_team || frm.doc.sales_team.length === 0) return;

        const salesPersons = frm.doc.sales_team
            .map(row => row.sales_person)
            .filter(Boolean);

        if (salesPersons.length === 0) return;

        let allSalesPersons = new Set(salesPersons);

        await Promise.all(salesPersons.map(sp => {
            return frappe.db.get_value('Sales Person', sp, 'parent_sales_person')
                .then(res => {
                    if (res && res.message && res.message.parent_sales_person) {
                        allSalesPersons.add(res.message.parent_sales_person);
                    }
                });
        }));

        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "User Permission",
                filters: {
                    allow: "Sales Person",
                    for_value: ["in", Array.from(allSalesPersons)]
                },
                fields: ["user"],
                limit_page_length: 100
            },
            callback: function(res) {
                if (!res.message || res.message.length === 0) return;

                const users = [...new Set(res.message.map(r => r.user))];

                users.forEach(user => {
                    frappe.call({
                        method: "frappe.client.get_list",
                        args: {
                            doctype: "DocShare",
                            filters: {
                                user: user,
                                share_doctype: frm.doc.doctype,
                                share_name: frm.doc.name
                            },
                            limit_page_length: 1
                        },
                        callback: function(res) {
                            if (res.message && res.message.length > 0) {
                                return;
                            }
                            frappe.call({
                                method: "frappe.client.insert",
                                args: {
                                    doc: {
                                        doctype: "DocShare",
                                        user: user,
                                        share_doctype: frm.doc.doctype,
                                        share_name: frm.doc.name,
                                        read: 1,
                                        write: 1,
                                        share: 1,
                                        submit: 1
                                    }
                                }
                            });
                        }
                    });
                });
            }
        });
    }
});
