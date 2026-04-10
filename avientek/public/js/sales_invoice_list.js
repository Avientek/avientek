// ── Client Script: "Auto Share for Invoice" (List view) ──
// Extend ERPNext's existing listview_settings instead of replacing them
const _si_orig = frappe.listview_settings['Sales Invoice'] || {};
const _si_orig_onload = _si_orig.onload;

Object.assign(_si_orig, {
    onload: function(listview) {
        // Call ERPNext's original onload first (Delivery Note / Payment bulk actions)
        if (_si_orig_onload) _si_orig_onload.call(this, listview);

        listview.page.add_actions_menu_item(__('Share with Sales Team Users'), async function() {
            const selected = listview.get_checked_items();
            if (!selected.length) {
                frappe.msgprint('Please select at least one Sales Invoice.');
                return;
            }

            frappe.confirm(
                __('Share {0} selected Sales Invoice with assigned and parent sales persons?', [selected.length]),
                async () => {
                    for (const so of selected) {
                        await share_sales_invoice_with_users(so.name);
                    }
                    frappe.msgprint(__('Sharing complete.'));
                }
            );
        });
    }
});

frappe.listview_settings['Sales Invoice'] = _si_orig;

async function share_sales_invoice_with_users(sales_invoice_name) {
    try {
        const { message: doc } = await frappe.call({
            method: "frappe.client.get",
            args: {
                doctype: "Sales Invoice",
                name: sales_invoice_name
            }
        });

        if (!doc.sales_team || doc.sales_team.length === 0) return;

        const salesPersons = doc.sales_team.map(row => row.sales_person).filter(Boolean);
        const allSalesPersons = new Set(salesPersons);

        await Promise.all(salesPersons.map(async sp => {
            const res = await frappe.db.get_value('Sales Person', sp, 'parent_sales_person');
            const parent = res && res.message && res.message.parent_sales_person;
            if (parent) allSalesPersons.add(parent);
        }));

        const res = await frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "User Permission",
                filters: {
                    allow: "Sales Person",
                    for_value: ["in", Array.from(allSalesPersons)]
                },
                fields: ["user"],
                limit_page_length: 1000
            }
        });

        if (!res.message || res.message.length === 0) return;

        const users = [...new Set(res.message.map(r => r.user))];

        for (const user of users) {
            let alreadyShared = false;
            try {
                const existing = await frappe.call({
                    method: "frappe.client.get_list",
                    args: {
                        doctype: "DocShare",
                        filters: {
                            user: user,
                            share_doctype: "Sales Invoice",
                            share_name: sales_invoice_name
                        },
                        fields: ["name"],
                        limit_page_length: 1
                    }
                });
                alreadyShared = existing.message && existing.message.length > 0;
            } catch (e) {
                alreadyShared = false;
            }

            if (!alreadyShared) {
                await frappe.call({
                    method: "frappe.client.insert",
                    args: {
                        doc: {
                            doctype: "DocShare",
                            user: user,
                            share_doctype: "Sales Invoice",
                            share_name: sales_invoice_name,
                            read: 1,
                            write: 1,
                            share: 1,
                            submit: 1
                        }
                    }
                });
            }
        }
    } catch (err) {
        console.error("Error sharing " + sales_invoice_name + ":", err);
    }
}
