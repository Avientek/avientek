// ── Client Script: "Delivery Note" ──
frappe.ui.form.on('Delivery Note', {
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
