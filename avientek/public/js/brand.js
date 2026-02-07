frappe.ui.form.on('Brand', {
    custom_company: function (frm) {
        if (!frm.doc.custom_company) {
            frm.set_value("custom_supplier_address", "");
            frm.set_value("custom_country", "");
            return;
        }

        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Address",
                filters: [
                    ["Dynamic Link", "link_doctype", "=", "Supplier"],
                    ["Dynamic Link", "link_name", "=", frm.doc.custom_company]
                ],
                fields: ["name"],
                limit_page_length: 1
            },
            callback: function (r) {
                if (r.message && r.message.length) {
                    let address_name = r.message[0].name;
                    frm.set_value("custom_supplier_address", address_name);
                    frappe.call({
                    method: "frappe.client.get",
                    args: {
                        doctype: "Address",
                        name: address_name
                    },
                    callback: function (addr) {
                        if (!addr.message) return;

                        frm.set_value("custom_country", addr.message.country);
                        frappe.call({
                            method: "frappe.contacts.doctype.address.address.get_address_display",
                            args: {
                                address_dict: address_name
                            },
                            callback: function (res) {
                                if (res.message) {
                                    frm.set_value("custom_address", res.message);
                                    
                                }
                            }
                        });
                    }
                });
                } else {
                    frm.set_value("custom_supplier_address", "");
                    frm.set_value("custom_address", "");
                }
            }
        });
    }
    // custom_company: function(frm) {
    //     console.log("Supplier field changed.");
    //     if(frm.doc.custom_company) {
    //         console.log("Supplier selected: " + frm.doc.custom_company);
    //         // Fetch all addresses of the selected supplier
    //         frappe.db.get_list('Address', {
    //             filters: {
    //                 supplier: frm.doc.custom_company
    //             },
    //             fields: ['name', 'address_line1', 'address_line2', 'city', 'state', 'pincode', 'country']
    //         }).then(addresses => {
    //             if(addresses.length > 0) {
    //                 // For simplicity, pick the first address
    //                 let addr = addresses[0];
    //                 frm.set_value('custom_supplier_address', addr.name);
    //                 // Combine address fields into display field
    //                 let full_address = [addr.address_line1, addr.address_line2, addr.city, addr.state, addr.pincode, addr.country].filter(Boolean).join(', ');
    //                 frm.set_value('custom_address', full_address);
    //             } else {
    //                 frm.set_value('custom_supplier_address', '');
    //                 frm.set_value('custom_address', '');
    //             }
    //         });
    //     } else {
    //         frm.set_value('custom_supplier_address', '');
    //         frm.set_value('custom_address', '');
    //     }
    // }
});
