// frappe.ui.form.on('Purchase Receipt', {
//     onload: function(frm) {
//         if (frm.doc.docstatus == 0) {
//             const purchase_order = frm.doc.items[0].purchase_order;
//             if(purchase_order) {
//                 frappe.db.get_value("Purchase Order", purchase_order, "plc_conversion_rate").then(r => {
//                     if(r && r.message) {
//                         setTimeout(() => {
//                             console.log()
//                             frm.set_value("plc_conversion_rate", r.message.plc_conversion_rate).then(() => {
//                                 frm.refresh_field("plc_conversion_rate");
//                             }).catch(err => {
//                                 console.log("Error setting plc_conversion_rate:", err);
//                             });
//                         }, 2000);
//                     }
//                 }).catch(err => {
//                     console.log("Error retrieving plc_conversion_rate:", err);
//                 });
//             }
//         }
//     }
// });
