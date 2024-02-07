frappe.ui.form.on('Company', {
    refresh: function(frm) {
        frm.add_custom_button(('Send ETA'), function() {
            frappe.confirm(
                'Are you sure?',
                function(){
                    sendSalesOrderPrints(frm);
                },
                function(){
                },
            );
        }, __('Manage'));
    }
});


function sendSalesOrderPrints(frm) {
    frappe.call({
        method: 'avientek.events.send_email.get_sales_orders',
        args:{
            company_name: frm.doc.name
        },
        callback: function(response) {
            const groupedData = response.message;
            if (Object.keys(groupedData).length !== 0) {
                for (const customerEmail in groupedData) {
                    const salesOrders = groupedData[customerEmail];
                    sendEmailToCustomer(frm, customerEmail, salesOrders);
                }
            } else {
                frappe.msgprint(('No Sales Orders found for this company.'));
                successMessageDisplayed = true;
            }
        }
    });
}    

var successMessageDisplayed = false;

function sendEmailToCustomer(frm, customerEmail, salesOrders) {
    frappe.call({
        method: 'avientek.events.send_email.send_email_to_customer',
        args: {
            customer_email: customerEmail,
            sales_orders: salesOrders
        },
        callback: function(response) {
            if (response.message === 'success' && !successMessageDisplayed) {
                frappe.msgprint(('Email sent successfully.'));
                successMessageDisplayed = true;
            } else if (response.message !== 'success') {
                frappe.msgprint(('Failed to send email. Please check the server logs.'));
            }

        }
    });
}