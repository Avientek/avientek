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


    setTimeout(() => {
        frappe.model.set_value(row.doctype,row.name, 'base_price_list_rate',(row.price_list_rate_copy+row.base_shipping+row.base_processing_charges+row.base_reward+row.base_levee+row.base_std_margin))},100)
    setTimeout(() => {
        frappe.model.set_value(row.doctype,row.name, 'price_list_rate',(row.price_list_rate_copy+row.shipping+row.processing_charges+row.reward+row.levee+row.std_margin)/conversion_rate)},100)

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
    console.log("rate calc")
    var row = locals[cdt][cdn]
    var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
    if (frm.doc.currency == company_currency){
        var conversion_rate = 1
    }
    else {
        var conversion_rate = frm.doc.conversion_rate
    }

    frappe.db.get_value('Brand',{'brand':row.brand},['shipping','processing_charges','reward','levee','std_margin'],(b) => {
                
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


frappe.ui.form.on('Quotation Item',{
    item_code:function(frm, cdt,cdn){
        console.log("item_code")
        var row = locals[cdt][cdn]
        setTimeout(() => {
            var row = locals[cdt][cdn]
            if(row.brand && row.base_price_list_rate){
                frappe.model.set_value(row.doctype,row.name,'price_list_rate_copy',row.base_price_list_rate)
                rate_calculation(frm,cdt,cdn)
            }
        },100)
    },
    price_list_rate_copy:function(frm,cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            row.shipping = flt(row.price_list_rate_copy) * flt(row.shipping_per) / 100;
            row.base_shipping = row.shipping*frm.doc.conversion_rate;
            row.processing_charges = flt(row.price_list_rate_copy) * flt(row.processing_charges_per) / 100;
            row.base_processing_charges = row.processing_charges*frm.doc.conversion_rate;
            row.reward = flt(row.price_list_rate_copy) * flt(row.reward_per) / 100;
            row.base_reward = row.reward*frm.doc.conversion_rate;
            row.levee = flt(row.price_list_rate_copy) * flt(row.levee_per) / 100;
            row.base_levee = row.levee*frm.doc.conversion_rate;
            row.std_margin = flt(row.price_list_rate_copy) * flt(row.std_margin_per) / 100;
            row.base_std_margin = row.std_margin*frm.doc.conversion_rate;
        }
        update_rates(frm,cdt,cdn)
    },
    shipping:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            if (row.shipping) {
                row.shipping_per = 100 * flt(row.shipping) / flt(row.price_list_rate_copy);
            }
            update_rates(frm,cdt,cdn)
        }
    },
    shipping_per:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            if (row.shipping_per) {
                row.shipping = flt(row.price_list_rate_copy) * flt(row.shipping_per) / 100;
                row.base_shipping = row.shipping*frm.doc.conversion_rate;
            }
            update_rates(frm,cdt,cdn)
        }
    },
    processing_charges:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            if (row.processing_charges) {
                row.processing_charges_per = 100 * flt(row.processing_charges) / flt(row.price_list_rate_copy);
            }
            update_rates(frm,cdt,cdn)
        }
    },
    processing_charges_per:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            if (row.processing_charges_per) {
                row.processing_charges = flt(row.price_list_rate_copy) * flt(row.processing_charges_per) / 100;
                row.base_processing_charges = row.processing_charges*frm.doc.conversion_rate;
            }
            update_rates(frm,cdt,cdn)
        }
    },
    reward:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            if (row.reward) {
                row.reward_per = 100 * flt(row.reward) / flt(row.price_list_rate_copy);
            }
            update_rates(frm,cdt,cdn)
        }
    },
    reward_per:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            if (row.reward_per) {
                row.reward = flt(row.price_list_rate_copy) * flt(row.reward_per) / 100;
                row.base_reward = row.reward*frm.doc.conversion_rate;
            }
            update_rates(frm,cdt,cdn)
        }
    },
    levee:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            if (row.levee) {
                row.levee_per = 100 * flt(row.levee) / flt(row.price_list_rate_copy);
            }
            update_rates(frm,cdt,cdn)
        }
    },
    levee_per:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            if (row.levee_per) {
                row.levee = flt(row.price_list_rate_copy) * flt(row.levee_per) / 100;
                row.base_levee = row.levee*frm.doc.conversion_rate;
            }
            update_rates(frm,cdt,cdn)
        }
    },
    std_margin:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            if (row.std_margin) {
                row.std_margin_per = 100 * flt(row.std_margin) / flt(row.price_list_rate_copy);
            }
            update_rates(frm,cdt,cdn)
        }
    },
    std_margin_per:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            if (row.std_margin_per) {
                row.std_margin = flt(row.price_list_rate_copy) * flt(row.std_margin_per) / 100;
                row.base_std_margin = row.std_margin*frm.doc.conversion_rate;
            }
            update_rates(frm,cdt,cdn)
        }
    },
    qty:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if(row.brand && row.price_list_rate_copy){
            update_rates(frm,cdt,cdn)
        }
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
        console.log("Workingggg",frm.doc.__islocal,frm.doc.selling_price_list)  
        if(frm.doc.__islocal === 1){
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

        console.log("frm.doc.total",frm.doc.total)
        console.log("total_shipping_per",(shipping_total/frm.doc.total)*100)

        frm.set_value('total_shipping_per', (shipping_total/frm.doc.total)*100);
        frm.set_value('total_processing_charges_per', (pc_total/frm.doc.total)*100);
        frm.set_value('total_reward_per', (reward_total/frm.doc.total)*100);
        frm.set_value('total_levee_per', (levee_total/frm.doc.total)*100);
        frm.set_value('total_std_margin_per', (std_total/frm.doc.total)*100);

        frm.set_value('base_total_shipping', base_shipping_total);
        frm.set_value('base_total_processing_charges', base_pc_total);
        frm.set_value('base_total_reward', base_reward_total);
        frm.set_value('base_total_levee', base_levee_total);
        frm.set_value('base_total_std_margin', base_std_total);
    },
})