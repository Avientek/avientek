frappe.ui.form.on('Quotation', {
    validate: function(frm) {
        console.log("hii")
        calculate_brand_summary(frm);
    }
});



function update_rates(frm,cdt,cdn){
    console.log("update rates")
    var row = locals[cdt][cdn]
    var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
    if (frm.doc.currency == company_currency){
        var conversion_rate = 1
    }
    else {
        var conversion_rate = frm.doc.conversion_rate
    }


    // frappe.model.set_value(row.doctype,row.name,'base_shipping',(row.shipping*conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'base_processing_charges',(row.processing_charges*conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'base_reward',(row.reward*conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'base_levee',(row.levee*conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'base_std_margin',(row.std_margin*conversion_rate))

    

    

    // frappe.model.set_value(row.doctype,row.name,'shipping_per',(((row.shipping/row.price_list_rate_copy)*100)*conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'shipping',(((row.shipping_per*row.price_list_rate_copy)/100)*conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'processing_charges',(row.processing_charges*conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'reward',(row.reward*conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'levee',(row.levee*conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'std_margin',(row.std_margin*conversion_rate))

    let tt = (row.price_list_rate_copy+row.base_shipping+row.base_processing_charges+row.base_reward+row.base_levee+row.base_std_margin)
    let duty = flt(row.price_list_rate_copy) * flt(row.custom_duty) / 100;
    let plc = frm.doc.plc_conversion_rate
    let conv = frm.doc.conversion_rate

    
    // console.log("dty",row.custom_duty)
    // console.log("tt,duty",tt,duty)
    setTimeout(() => {
        // if (!frm.doc.amended_from){
        frappe.model.set_value(row.doctype,row.name, 'base_price_list_rate',row.usd_price_list_rate_with_margin*plc*conv)
        frappe.model.set_value(row.doctype,row.name, 'custom_duty_charges',duty)
        frappe.model.set_value(row.doctype,row.name,'custom_standard_price_',row.price_list_rate)
        frappe.model.set_value(row.doctype,row.name,'custom_special_price',row.price_list_rate)
        
    },100)

    setTimeout(() => {
        // if (!frm.doc.amended_from){
            // frappe.model.set_value(row.doctype,row.name, 'price_list_rate',(row.usd_price_list_rate_with_margin*plc*conv))

        },100)
        

    frappe.model.set_value(row.doctype,row.name,'base_total_shipping',(row.base_shipping*row.qty))
    frappe.model.set_value(row.doctype,row.name,'base_total_processing_charges',(row.base_processing_charges*row.qty))
    frappe.model.set_value(row.doctype,row.name,'base_total_reward',(row.base_reward*row.qty))
    frappe.model.set_value(row.doctype,row.name,'base_total_levee',(row.base_levee*row.qty))
    frappe.model.set_value(row.doctype,row.name,'base_total_std_margin',(row.base_std_margin*row.qty))

    frappe.model.set_value(row.doctype,row.name,'total_shipping',(row.shipping*row.qty))
    frappe.model.set_value(row.doctype,row.name,'total_processing_charges',(row.processing_charges*row.qty))
    frappe.model.set_value(row.doctype,row.name,'total_reward',(row.reward*row.qty))
    frappe.model.set_value(row.doctype,row.name,'total_levee',(row.levee*row.qty))
    frappe.model.set_value(row.doctype,row.name,'total_std_margin',(row.std_margin*row.qty))

    frm.trigger('calculate_total')

}

function rate_calculation(frm,cdt,cdn){
// console.log("rate calc")
var row = locals[cdt][cdn]
var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
if (!frm.doc.amended_from){
if (frm.doc.currency == company_currency){
    var conversion_rate = 1
}
else {
    var conversion_rate = frm.doc.conversion_rate
}

if(!row.custom_duty){
    frappe.call({
        'method': 'avientek.events.item.get_custom_duty',
        'args':{
            'item': row.item_code,
            'company': frm.doc.company,
        },
        callback: (r) => {
            if(!r.exc) {
                // console.log("r.messageeeeeee dty",r.message)
                frappe.model.set_value(row.doctype,row.name,'custom_duty',r.message)
            }
        }
    })
}
}

frappe.db.get_value('Brand',{'brand':row.brand},['shipping','processing_charges','reward','levee','std_margin','custom_finance_','custom_transport'],(b) => {
            
    // var shipping = (row.price_list_rate_copy*b.shipping) /100
    // var processing_charges = (row.price_list_rate_copy*b.processing_charges) /100
    // var reward = (row.price_list_rate_copy*b.reward) /100
    // var levee = (row.price_list_rate_copy*b.levee) /100
    // var std_margin = (row.price_list_rate_copy*b.std_margin) /100

    frappe.model.set_value(row.doctype,row.name,'shipping_per',(b.shipping))
    frappe.model.set_value(row.doctype,row.name,'processing_charges_per',(b.processing_charges))
    frappe.model.set_value(row.doctype,row.name,'reward_per',(b.reward))
    frappe.model.set_value(row.doctype,row.name,'levee_per',(b.levee))
    frappe.model.set_value(row.doctype,row.name,'std_margin_per',(b.std_margin))
    frappe.model.set_value(row.doctype,row.name,'custom_finance_',(b.custom_finance_))
    frappe.model.set_value(row.doctype,row.name,'custom_transport_',(b.custom_transport))
    frappe.call({
        'method': 'avientek.events.item.get_custom_duty',
        'args':{
            'item': row.item_code,
            'company': frm.doc.company,
        },
        callback: (r) => {
            if(!r.exc) {
                console.log("Custom duty result", r.message);
                // console.log("r.messageeeeeee dty",r.message)
                frappe.model.set_value(row.doctype,row.name,'custom_customs_',r.message)
            }
        }
    })
   

    // frappe.model.set_value(row.doctype,row.name,'base_shipping',(shipping))
    // frappe.model.set_value(row.doctype,row.name,'base_processing_charges',(processing_charges))
    // frappe.model.set_value(row.doctype,row.name,'base_reward',(reward))
    // frappe.model.set_value(row.doctype,row.name,'base_levee',(levee))
    // frappe.model.set_value(row.doctype,row.name,'base_std_margin',(std_margin))

    // frappe.model.set_value(row.doctype,row.name,'shipping',(shipping/conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'processing_charges',(processing_charges/conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'reward',(reward/conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'levee',(levee/conversion_rate))
    // frappe.model.set_value(row.doctype,row.name,'std_margin',(std_margin/conversion_rate))

    update_rates(frm,cdt,cdn)
    

})

}

function calculate_all(frm, cdt, cdn) {
    let row = locals[cdt][cdn];

    function toFloat(val) {
        if (!val) return 0;
        if (typeof val === "string") {
            val = val.replace(/[^\d.-]/g, '');
        }
        return parseFloat(val) || 0;
    }

    let qty = toFloat(row.qty);
    if (qty <= 0) qty = 1; // Prevent division or multiplication issues

    let std_price = toFloat(row.custom_standard_price_);
    let sp = toFloat(row.custom_special_price);

    let shipping_per = toFloat(row.shipping_per);
    let finance_per = toFloat(row.custom_finance_);
    let transport_per = toFloat(row.custom_transport_);
    let reward_per = toFloat(row.reward_per);
    let incentive_per = toFloat(row.custom_incentive_);
    let markup_per = toFloat(row.custom_markup_);
    let customs_per = toFloat(row.custom_customs_);

    let shipping = (shipping_per * std_price / 100) * qty;
    let finance = (finance_per * sp / 100) * qty;
    let transport = (transport_per * std_price / 100) * qty;
    let reward = (reward_per * sp / 100) * qty;

    let base_amount = (sp * qty) + shipping + finance + transport + reward;
    let incentive = incentive_per * base_amount / 100;
    let cogs = base_amount + incentive;

    let markup = markup_per * cogs / 100;
    let total = cogs + markup;

    let customs = customs_per * total / 100;
    let selling_price = total + customs;

    let margin_percent = total !== 0 ? (markup / total) * 100 : 0;
    let margin_value = (margin_percent / 100) * total;

    // Set values
    frappe.model.set_value(cdt, cdn, 'shipping', shipping);
    frappe.model.set_value(cdt, cdn, 'custom_finance_value', finance);
    frappe.model.set_value(cdt, cdn, 'custom_transport_value', transport);
    frappe.model.set_value(cdt, cdn, 'reward', reward);
    frappe.model.set_value(cdt, cdn, 'custom_incentive_value', incentive);
    frappe.model.set_value(cdt, cdn, 'custom_markup_value', markup);
    frappe.model.set_value(cdt, cdn, 'custom_cogs', cogs);
    frappe.model.set_value(cdt, cdn, 'custom_total_', total);
    frappe.model.set_value(cdt, cdn, 'custom_margin_', margin_percent);
    frappe.model.set_value(cdt, cdn, 'custom_margin_value', margin_value);
    frappe.model.set_value(cdt, cdn, 'custom_customs_value', customs);
    frappe.model.set_value(cdt, cdn, 'custom_selling_price', selling_price);
}


function calculate_brand_summary(frm) {
    let brand_data = {};

    frm.doc.items.forEach(row => {
        let brand = row.brand;
        if (!brand_data[brand]) {
            brand_data[brand] = {
                shipping: 0,
                shipping_percent: 0,
                finance: 0,
                finance_percent: 0,
                transport: 0,
                transport_percent: 0,
                reward: 0,
                reward_percent: 0,
                incentive: 0,
                incentive_percent: 0,
                customs: 0,
                customs_percent: 0,
                total_cost: 0,
                total_selling: 0,
                margin: 0,
                margin_percent: 0,
                item_count: 0
            };
        }

        function toFloat(val) {
            if (!val) return 0;
            if (typeof val === "string") {
                val = val.replace(/[^\d.-]/g, '');
            }
            return parseFloat(val) || 0;
        }

        let qty = flt(row.qty) || 1;

        let std_price = toFloat(row.custom_standard_price_);
        let sp = flt(row.custom_special_price);
        let shipping = ((flt(row.shipping_per) * std_price) / 100) * qty;
        let finance = ((flt(row.custom_finance_) * sp) / 100) * qty;
        let transport = ((flt(row.custom_transport_) * std_price) / 100) * qty;
        let reward = ((flt(row.reward_per) * sp) / 100) * qty;

        let base_amount = (sp * qty) + shipping + finance + transport + reward;

        let incentive_percent = flt(row.custom_incentive_);
        let incentive = (base_amount * incentive_percent / 100);

        let cogs = base_amount + incentive;

        let markup = (flt(row.custom_markup_) * cogs / 100);
        let total = cogs + markup;

        let customs_percent = flt(row.custom_customs_);
        let customs = (customs_percent * total / 100);

        let selling_price = total + customs;

        let margin = markup;
        let margin_percent = (markup / (total || 1)) * 100;

        // Sum up amounts
        brand_data[brand].shipping += shipping;
        brand_data[brand].shipping_percent += flt(row.shipping_per);
        brand_data[brand].finance += finance;
        brand_data[brand].finance_percent += flt(row.custom_finance_);
        brand_data[brand].transport += transport;
        brand_data[brand].transport_percent += flt(row.custom_transport_);
        brand_data[brand].reward += reward;
        brand_data[brand].reward_percent += flt(row.reward_per);
        brand_data[brand].incentive += incentive;
        brand_data[brand].incentive_percent += incentive_percent;
        brand_data[brand].customs += customs;
        brand_data[brand].customs_percent += customs_percent;
        brand_data[brand].total_cost += cogs;
        brand_data[brand].total_selling += selling_price;
        brand_data[brand].margin += margin;
        brand_data[brand].margin_percent += margin_percent;
        brand_data[brand].item_count += 1;
    });

    frm.clear_table('custom_brand_summary');

    Object.keys(brand_data).forEach(brand => {
        let data = brand_data[brand];
        let count = data.item_count;

        frm.add_child('custom_brand_summary', {
            brand: brand,
            shipping: data.shipping,
            shipping_percent: data.shipping_percent / count,
            finance: data.finance,
            finance_percent: data.finance_percent / count,
            transport: data.transport,
            transport_percent: data.transport_percent / count,
            reward: data.reward,
            reward_percent: data.reward_percent / count,
            incentive: data.incentive,
            incentive_percent: data.incentive_percent / count,
            customs: data.customs,
            customs_: data.customs_percent / count,
            total_cost: data.total_cost,
            total_selling: data.total_selling,
            margin: data.margin,
            margin_percent: data.margin_percent / count
        });
    });

    frm.refresh_field('custom_brand_summary');
    console.log("✅ Brand summary updated with qty considered.");
}
function calculate_custom_rate(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    if (row.qty > 0) {
        let special_rate = row.custom_selling_price / row.qty;
        frappe.model.set_value(cdt, cdn, 'custom_special_rate', special_rate);
        frappe.model.set_value(cdt, cdn, 'rate', special_rate);
    }
}

// frappe.ui.form.on('Quotation', {
//     refresh(frm) {
//         frm.fields_dict.items.grid.get_field('items').grid.on('fields_rendered', function() {
//             frm.fields_dict.items.grid.grid_rows.forEach(row => {
//                 row.on('field_change', () => calculate_all(row.doc, frm));
//             });
//         });
//     }
// });




frappe.ui.form.on('Quotation Item',{
item_code:function(frm, cdt,cdn){
    var row = locals[cdt][cdn]
    setTimeout(() => {
        var row = locals[cdt][cdn]
        frappe.db.get_value("Item Price", {"item_code": row.item_code,"price_list":frm.doc.selling_price_list}, "price_list_rate", (d) => {
            // console.log("custom duty",d.price_list_rate)
            if(d.price_list_rate){
                frappe.model.set_value(row.doctype,row.name,'usd_price_list_rate',d.price_list_rate)
                frappe.model.set_value(row.doctype,row.name,'usd_price_list_rate_with_margin',d.price_list_rate)
                

            }
        });
        // if(row.brand && row.base_price_list_rate){
        //     console.log("item",row.item_code)
        //     frappe.model.set_value(row.doctype,row.name,'price_list_rate_copy',row.base_price_list_rate)
        // }
        rate_calculation(frm,cdt,cdn)
       
    },1000)
},
usd_price_list_rate_with_margin:function(frm,cdt,cdn) {
    var row = locals[cdt][cdn]
    if(row.usd_price_list_rate_with_margin){
        let plc = frm.doc.plc_conversion_rate
        let conv = frm.doc.conversion_rate
        // console.log("plc conv\n\n",frm.doc.plc_conversion_rate,frm.doc.conversion_rate)
        // if(!frm.doc.plc_conversion_rate){
        //     plc=1
        // }
        if(!frm.doc.plc_conversion_rate || (frm.doc.currency == frm.doc.price_list_currency)){
            plc = 1
        }
        if(!frm.doc.conversion_rate){
            conv =1
        }
        
        // console.log("plc conv\n\n",plc,conv)
        // console.log("copyyyyyyyyyyyy\n\n",(row.usd_price_list_rate_with_margin*plc*conv))

        frappe.model.set_value(row.doctype,row.name,'price_list_rate_copy',(row.usd_price_list_rate_with_margin*plc*conv))
      
    }
},
price_list_rate_copy:function(frm,cdt,cdn){
    var row = locals[cdt][cdn]
    if(row.brand && row.price_list_rate_copy){
        // row.shipping = (flt(row.price_list_rate_copy) * flt(row.shipping_per) / 100) / frm.doc.conversion_rate;
        row.base_shipping = row.shipping*frm.doc.conversion_rate;
        row.processing_charges = (flt(row.price_list_rate_copy) * flt(row.processing_charges_per) / 100)/ frm.doc.conversion_rate;
        row.base_processing_charges = row.processing_charges*frm.doc.conversion_rate;
        // row.reward = (flt(row.price_list_rate_copy) * flt(row.reward_per) / 100)/ frm.doc.conversion_rate;
        row.base_reward = row.reward*frm.doc.conversion_rate;
        row.levee = (flt(row.price_list_rate_copy) * flt(row.levee_per) / 100)/ frm.doc.conversion_rate;
        row.base_levee = row.levee*frm.doc.conversion_rate;
        row.std_margin = (flt(row.price_list_rate_copy) * flt(row.std_margin_per) / 100)/ frm.doc.conversion_rate;
        row.base_std_margin = row.std_margin*frm.doc.conversion_rate;
    }
    update_rates(frm,cdt,cdn)
},
custom_special_price:function(frm,cdt,cdn){
    calculate_all(frm, cdt, cdn);
    calculate_custom_rate(frm, cdt, cdn);
},
custom_incentive_(frm, cdt, cdn) {
    calculate_all(frm, cdt, cdn);
    calculate_custom_rate(frm, cdt, cdn);
},
custom_markup_(frm,cdt,cdn){
    // console.log("Markup : ",markup )
    calculate_all(frm, cdt, cdn);
    calculate_custom_rate(frm, cdt, cdn);
},
custom_customs_(frm,cdt,cdn){
    calculate_all(frm, cdt, cdn);
    calculate_custom_rate(frm, cdt, cdn);
    var row = locals[cdt][cdn]
    if (row.custom_customs_) {
        let final_rate = (row.custom_customs_ / 100) * row.valuation_rate;
        frappe.model.set_value(cdt, cdn, 'custom_final_valuation_rate', final_rate);
    } else {
        frappe.model.set_value(cdt, cdn, 'custom_final_valuation_rate', 0);
    }
    
},
custom_finance_(frm,cdt,cdn){
    calculate_all(frm, cdt, cdn);
},
custom_transport_(frm,cdt,cdn){
    calculate_all(frm, cdt, cdn);
},
// custom_selling_price(frm, cdt, cdn) {
//         calculate_custom_rate(frm, cdt, cdn);
// },


shipping:function(frm, cdt,cdn){
    var row = locals[cdt][cdn]
    // if(row.brand && row.price_list_rate_copy){
        // if (row.shipping) {
        // row.shipping_per = 100 * flt(row.shipping) / flt(row.price_list_rate_copy);
    let qty = flt(row.qty) || 1;
    let standard_price = flt(row.custom_standard_price_) * qty;
    row.shipping_per = 100 * flt(row.shipping) / standard_price;
        // }
        // update_rates(frm,cdt,cdn)
      
    calculate_all(frm, cdt, cdn);
    // }

},
shipping_per:function(frm, cdt,cdn){
    var row = locals[cdt][cdn]
    // if(row.brand && row.price_list_rate_copy){
        // if (row.shipping_per) {
        let qty = flt(row.qty) || 1;
        let sp = flt(row.custom_standard_price_) * qty;

        row.shipping = (flt(row.shipping_per) * sp / 100);
        // row.shipping = (flt(row.price_list_rate_copy) * flt(row.shipping_per) / 100) / frm.doc.conversion_rate;
        row.base_shipping = row.shipping*frm.doc.conversion_rate;
        // }
        // update_rates(frm,cdt,cdn)
        calculate_all(frm, cdt, cdn);
        calculate_custom_rate(frm, cdt, cdn);
    // }

},
processing_charges:function(frm, cdt,cdn){
    var row = locals[cdt][cdn]
    if(row.brand && row.price_list_rate_copy){
        // if (row.processing_charges) {
            row.processing_charges_per = 100 * flt(row.processing_charges) / flt(row.price_list_rate_copy);
        // }
        update_rates(frm,cdt,cdn)
    }

},
processing_charges_per:function(frm, cdt,cdn){
    var row = locals[cdt][cdn]
    if(row.brand && row.price_list_rate_copy){
        // if (row.processing_charges_per) {
            row.processing_charges = (flt(row.price_list_rate_copy) * flt(row.processing_charges_per) / 100) / frm.doc.conversion_rate;
            row.base_processing_charges = row.processing_charges*frm.doc.conversion_rate;
        // }
        update_rates(frm,cdt,cdn)
    }

},
reward:function(frm, cdt,cdn){
    var row = locals[cdt][cdn]
    // if(row.brand && row.price_list_rate_copy){
        // if (row.reward) {
            // row.reward_per = 100 * flt(row.reward) / flt(row.price_list_rate_copy);
            let qty = flt(row.qty) || 1;
            let special_price_total = flt(row.custom_special_price) * qty;
            row.reward_per = 100 * flt(row.reward) / special_price_total;
        // }
        // update_rates(frm,cdt,cdn)
        calculate_all(frm, cdt, cdn);
    // }

},
reward_per:function(frm, cdt,cdn){
    var row = locals[cdt][cdn]
    if(row.brand && row.price_list_rate_copy){
        // if (row.reward_per) {
            // row.reward = (flt(row.price_list_rate_copy) * flt(row.reward_per) / 100)/ frm.doc.conversion_rate;
            let qty = flt(row.qty) || 1;
            let special_price_total = flt(row.custom_special_price) * qty;
            row.reward = (flt(row.reward_per) * special_price_total / 100);
            row.base_reward = row.reward*frm.doc.conversion_rate;
        // }
        // update_rates(frm,cdt,cdn)
        calculate_all(frm, cdt, cdn);
    }

},
levee:function(frm, cdt,cdn){
    var row = locals[cdt][cdn]
    if(row.brand && row.price_list_rate_copy){
        // if (row.levee) {
            row.levee_per = 100 * flt(row.levee) / flt(row.price_list_rate_copy);
        // }
        update_rates(frm,cdt,cdn)
    }

},
levee_per:function(frm, cdt,cdn){
    var row = locals[cdt][cdn]
    if(row.brand && row.price_list_rate_copy){
        // if (row.levee_per) {
            row.levee = (flt(row.price_list_rate_copy) * flt(row.levee_per) / 100)/ frm.doc.conversion_rate;
            row.base_levee = row.levee*frm.doc.conversion_rate;
        // }
        update_rates(frm,cdt,cdn)
    }

},
std_margin:function(frm, cdt,cdn){
    var row = locals[cdt][cdn]
    if(row.brand && row.price_list_rate_copy){
        // if (row.std_margin) {
            row.std_margin_per = 100 * flt(row.std_margin) / flt(row.price_list_rate_copy);
        // }
        update_rates(frm,cdt,cdn)
    }

},
std_margin_per:function(frm, cdt,cdn){
    var row = locals[cdt][cdn]
    if(row.brand && row.price_list_rate_copy){
        // if (row.std_margin_per) {
            row.std_margin = (flt(row.price_list_rate_copy) * flt(row.std_margin_per) / 100)/ frm.doc.conversion_rate;
            row.base_std_margin = row.std_margin*frm.doc.conversion_rate;
        // }
        update_rates(frm,cdt,cdn)
    }
s
},

qty:function(frm, cdt,cdn){
    calculate_all(frm, cdt, cdn);
    calculate_custom_rate(frm, cdt, cdn);
    // var row = locals[cdt][cdn]
    // if(row.brand && row.price_list_rate_copy){
    //     update_rates(frm,cdt,cdn)
    // }
},
before_save:function(frm,cdt,cdn){
    frm.trigger('calculate_total')
},
items_remove:function(frm){
    frm.trigger('calculate_total')
},

})

function toggle_item_grid_columns(frm){
var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
var item_grid = frm.fields_dict["items"].grid;
$.each(["base_shipping","base_processing_charges","base_reward","base_levee","base_std_margin","base_total_shipping","base_total_processing_charges",
    "base_total_reward","base_total_levee","base_total_std_margin",
    "base_total_shipping","base_total_processing_charges","base_total_reward","base_total_levee","base_total_std_margin"], function(i, fname) {
    if(frappe.meta.get_docfield(item_grid.doctype, fname))
        item_grid.toggle_display(fname, frm.doc.currency != company_currency);
    if(frappe.meta.get_docfield("Quotation", fname))
        frm.toggle_display(fname, frm.doc.currency != company_currency);
});
}

frappe.ui.form.on('Quotation',{
before_save:function(frm){
    frm.trigger('calculate_total')
},
items_on_form_rendered:function(frm){
    var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
    frm.set_currency_labels([
        "base_shipping","base_processing_charges","base_reward","base_levee","base_std_margin","base_total_shipping","base_total_processing_charges","base_total_reward","base_total_levee","base_total_std_margin"
    ], company_currency, "items");

    frm.set_currency_labels([
        "base_total_shipping","base_total_processing_charges","base_total_reward","base_total_levee","base_total_std_margin"
    ], company_currency);

    var trans_currency = frm.doc.currency
    frm.set_currency_labels([
        "shipping","processing_charges","reward","levee","std_margin","total_shipping","total_processing_charges","total_reward","total_levee","total_std_margin"
    ], trans_currency, "items");

    frm.set_currency_labels([
        "total_shipping","total_processing_charges","total_reward","total_levee","total_std_margin"
    ], trans_currency);

    toggle_item_grid_columns(frm);
},
refresh:function(frm){ 
    // console.log("Workingggg",frm.doc.__islocal,frm.doc.selling_price_list)  

    if(frm.doc.__islocal === 1){
        if(frm.doc.selling_price_list){
            setTimeout(() => {
                frm.doc.items.forEach((item) =>{
                    if(item.brand && item.base_price_list_rate){
                        if(!frm.doc.amended_from){
                        frappe.model.set_value(item.doctype,item.name,'price_list_rate_copy',item.base_price_list_rate)
                        rate_calculation(frm,item.doctype,item.name)
                    }
                }
                });
            },100)
        }
    }     
    frm.set_query("selling_price_list", function() {
        return {
            "filters": {
                "currency": frm.doc.currency
            }
        }
    });
    var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
    frm.set_currency_labels([
        "base_shipping","base_processing_charges","base_reward","base_levee","base_std_margin","base_total_shipping","base_total_processing_charges","base_total_reward","base_total_levee","base_total_std_margin"
    ], company_currency, "items");

    frm.set_currency_labels([
        "base_total_shipping","base_total_processing_charges","base_total_reward","base_total_levee","base_total_std_margin"
    ], company_currency);

    var trans_currency = frm.doc.currency
    frm.set_currency_labels([
        "shipping","processing_charges","reward","levee","std_margin","total_shipping","total_processing_charges","total_reward","total_levee","total_std_margin"
    ], trans_currency, "items");

    frm.set_currency_labels([
        "total_shipping","total_processing_charges","total_reward","total_levee","total_std_margin"
    ], trans_currency);

    toggle_item_grid_columns(frm);
},
onload:function(frm){
    var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
    frm.set_currency_labels([
        "base_shipping","base_processing_charges","base_reward","base_levee","base_std_margin","base_total_shipping","base_total_processing_charges","base_total_reward","base_total_levee","base_total_std_margin"
    ], company_currency, "items");
    frm.set_currency_labels([
        "base_total_shipping","base_total_processing_charges","base_total_reward","base_total_levee","base_total_std_margin"
    ], company_currency);

    var trans_currency = frm.doc.currency
    frm.set_currency_labels([
        "shipping","processing_charges","reward","levee","std_margin","total_shipping","total_processing_charges","total_reward","total_levee","total_std_margin"
    ], trans_currency, "items");
    frm.set_currency_labels([
        "total_shipping","total_processing_charges","total_reward","total_levee","total_std_margin"
    ], trans_currency);
},
currency:function(frm){
    toggle_item_grid_columns(frm);
},
customer:function(frm){
    toggle_item_grid_columns(frm);
},
conversion_rate:function(frm){
    toggle_item_grid_columns(frm);
},
selling_price_list:function(frm){
    if(frm.doc.selling_price_list){
        setTimeout(() => {
            frm.doc.items.forEach((item) =>{
                if(item.brand && item.base_price_list_rate){
                    frappe.model.set_value(item.doctype,item.name,'price_list_rate_copy',item.base_price_list_rate)
                    rate_calculation(frm,item.doctype,item.name)
                }
            });
        },100)
    }
},
calculate_total: function (frm){
    // triggers when you change row value
    let doc = frm.doc;

    let shipping_total = 0;
    let pc_total = 0;
    let reward_total = 0;
    let levee_total = 0;
    let std_total = 0;
    let custom_total = 0;

    // let per_shipping_total = 0;
    // let per_pc_total = 0;
    // let per_reward_total = 0;
    // let per_levee_total = 0;
    // let per_std_total = 0;

    let base_shipping_total = 0;
    let base_pc_total = 0;
    let base_reward_total = 0;
    let base_levee_total = 0;
    let base_std_total = 0;

    for (let i in doc.items){
        if (doc.items[i].total_shipping){
            shipping_total += doc.items[i].total_shipping;
        }       
        if (doc.items[i].total_processing_charges){
            pc_total += doc.items[i].total_processing_charges;
        }       
        if (doc.items[i].total_reward){
            reward_total += doc.items[i].total_reward;
        }       
        if (doc.items[i].total_levee){
            levee_total += doc.items[i].total_levee;
        }       
        if (doc.items[i].total_std_margin){
            std_total += doc.items[i].total_std_margin;
        } 
        if (doc.items[i].custom_duty_charges){
            custom_total += doc.items[i].custom_duty_charges;
        } 

        // if (doc.items[i].shipping_per){
        //     per_shipping_total += doc.items[i].shipping_per;
        // }       
        // if (doc.items[i].processing_charges_per){
        //     per_pc_total += doc.items[i].processing_charges_per;
        // }       
        // if (doc.items[i].reward_per){
        //     per_reward_total += doc.items[i].reward_per;
        // }       
        // if (doc.items[i].levee_per){
        //     per_levee_total += doc.items[i].levee_per;
        // }       
        // if (doc.items[i].std_margin_per){
        //     per_std_total += doc.items[i].std_margin_per;
        // } 

        if (doc.items[i].base_total_shipping){
            base_shipping_total += doc.items[i].base_total_shipping;
        }       
        if (doc.items[i].base_processing_charges){
            base_pc_total += doc.items[i].base_processing_charges;
        }       
        if (doc.items[i].base_reward){
            base_reward_total += doc.items[i].base_reward;
        }       
        if (doc.items[i].base_levee){
            base_levee_total += doc.items[i].base_levee;
        }       
        if (doc.items[i].base_std_margin){
            base_std_total += doc.items[i].base_std_margin;
        }       
    }

    frm.refresh_field('items');
    frm.set_value('total_shipping', shipping_total);
    frm.set_value('total_processing_charges', pc_total);
    frm.set_value('total_reward', reward_total);
    frm.set_value('total_levee', levee_total);
    frm.set_value('total_std_margin', std_total);

    // console.log("frm.doc.total",frm.doc.total)
    // console.log("total_shipping_per",(shipping_total/frm.doc.total)*100)

    frm.set_value('total_shipping_per', (shipping_total/frm.doc.total)*100);
    frm.set_value('total_processing_charges_per', (pc_total/frm.doc.total)*100);
    frm.set_value('total_reward_per', (reward_total/frm.doc.total)*100);
    frm.set_value('total_levee_per', (levee_total/frm.doc.total)*100);
    frm.set_value('total_std_margin_per', (std_total/frm.doc.total)*100);
    frm.set_value('total_custom_duty_charges', (custom_total/frm.doc.total)*100);

    frm.set_value('base_total_shipping', base_shipping_total);
    frm.set_value('base_total_processing_charges', base_pc_total);
    frm.set_value('base_total_reward', base_reward_total);
    frm.set_value('base_total_levee', base_levee_total);
},
})