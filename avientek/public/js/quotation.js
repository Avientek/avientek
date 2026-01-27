frappe.ui.form.on('Quotation', {
    validate: function(frm) {
        calculate_brand_summary(frm);
    },
    custom_shipping_mode: function (frm) {
        update_items_shipping_percent(frm);
    },
    party_name: function(frm) {
        if (!frm.doc.party_name) return;
        if (frm.doc.quotation_to !== 'Customer') {
            // Clear values if not matching
            frm.set_value('custom_credit_limit', 0);
            frm.set_value('custom_outstanding', 0);
            frm.set_value('custom_overdue', 0);
            return;
        }

        let company = frm.doc.company;

        // 1️⃣ Get Credit Limit from Customer Master
        frappe.db.get_doc('Customer', frm.doc.party_name).then(customer_doc => {
            let credit_limit = 0;

            if (customer_doc.credit_limits) {
                let limit_entry = customer_doc.credit_limits.find(l => l.company === company);
                if (limit_entry) {
                    credit_limit = limit_entry.credit_limit;
                }
            }

            frm.set_value('custom_credit_limit', credit_limit);
            if (customer_doc.payment_terms) {
                frm.set_value('custom_existing_payment_term', customer_doc.payment_terms);
            } else {
                frm.set_value('custom_existing_payment_term', '');
            }
            // 2️⃣ Get Outstanding Credit (Invoices)
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'Sales Invoice',
                    filters: {
                        customer: frm.doc.party_name,
                        company: company,
                        docstatus: 1
                    },
                    fields: ['outstanding_amount']
                },
                callback: function(r) {
                    let outstanding = 0;
                    if (r.message) {
                        r.message.forEach(inv => {
                            outstanding += flt(inv.outstanding_amount);
                        });
                    }
                    frm.set_value('custom_outstanding', outstanding);
                }
            });

            // 3️⃣ Get Overdue (Open Sales Orders)
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'Sales Order',
                    filters: {
                        customer: frm.doc.party_name,
                        company: company,
                        docstatus: 1, // submitted
                        per_billed: ["<", 100] // not fully billed
                    },
                    fields: ['grand_total']
                },
                callback: function(r) {
                    let overdue = 0;
                    if (r.message) {
                        r.message.forEach(so => {
                            overdue += flt(so.grand_total);
                        });
                    }
                    frm.set_value('custom_overdue', overdue);
                }
            });

        });
    },
    customer: function(frm) {
        if (!frm.doc.customer) return;

        let company = frm.doc.company;

        // 1️⃣ Get Credit Limit from Customer Master
        frappe.db.get_doc('Customer', frm.doc.customer).then(customer_doc => {
            let credit_limit = 0;

            if (customer_doc.credit_limits) {
                let limit_entry = customer_doc.credit_limits.find(l => l.company === company);
                if (limit_entry) {
                    credit_limit = limit_entry.credit_limit;
                }
            }

            frm.set_value('credit_limit', credit_limit);

            // 2️⃣ Get Outstanding Credit (Invoices)
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'Sales Invoice',
                    filters: {
                        customer: frm.doc.customer,
                        company: company,
                        docstatus: 1
                    },
                    fields: ['outstanding_amount']
                },
                callback: function(r) {
                    let outstanding = 0;
                    if (r.message) {
                        r.message.forEach(inv => {
                            outstanding += flt(inv.outstanding_amount);
                        });
                    }
                    frm.set_value('outstanding_credit', outstanding);
                }
            });

            // 3️⃣ Get Overdue (Open Sales Orders)
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'Sales Order',
                    filters: {
                        customer: frm.doc.customer,
                        company: company,
                        docstatus: 1, // submitted
                        per_billed: ["<", 100] // not fully billed
                    },
                    fields: ['grand_total']
                },
                callback: function(r) {
                    let overdue = 0;
                    if (r.message) {
                        r.message.forEach(so => {
                            overdue += flt(so.grand_total);
                        });
                    }
                    frm.set_value('overdue', overdue);
                }
            });

        });
    },

   
    custom_apply_discount: function(frm) {
        
        if (!frm.doc.custom_discount_amount_value) {
            frappe.msgprint("Please enter discount amount");
            return;
        }

        frappe.call({
            method: "avientek.events.quotation.apply_discount",
            args: {
                doc: frm.doc,
                discount_amount: frm.doc.custom_discount_amount_value
            },
            callback: function(r) {
                if (r.message) {
                    frm.set_value("custom_discount_amount_value", r.message.custom_discount_amount_value);
                    frm.set_value("custom_discount_", r.message.custom_discount_);
                    frm.custom_applying_bulk_discount = true;

                    // only update items returned from server (newly discounted)
                    (r.message.items || []).forEach(it => {
                        console.log("Updating item:", it);
                        frappe.model.set_value("Quotation Item", it.name, "custom_special_rate", it.custom_special_rate);
                        frappe.model.set_value("Quotation Item", it.name, "custom_selling_price", it.custom_selling_price);
                        frappe.model.set_value("Quotation Item", it.name, "custom_margin_value", it.custom_margin_value);
                        frappe.model.set_value("Quotation Item", it.name, "custom_margin_", it.custom_margin_);
                        frappe.model.set_value("Quotation Item", it.name, "rate", it.custom_special_rate);
                        frappe.model.set_value("Quotation Item", it.name, "amount", it.custom_selling_price);
                        frappe.model.set_value("Quotation Item", it.name, "custom_total_", it.custom_selling_price);
                        frappe.model.set_value("Quotation Item", it.name, "custom_discount_amount_value", it.custom_discount_amount_value);
                        frappe.model.set_value("Quotation Item", it.name, "custom_discount_amount_qty", it.custom_discount_amount_qty);
                    });
                    frm.custom_applying_bulk_discount = false;


                    frm.refresh_field("items");
                    frm.trigger("calculate_taxes_and_totals");
                }
            }
        });
    },
    custom_incentive_(frm) {
        normalize_incentive_percent(frm, "percent");
        distribute_incentive(frm);
    },

    custom_incentive_amount(frm) {
        normalize_incentive_percent(frm, "amount");
        distribute_incentive(frm);
    },

    custom_distribute_incentive_based_on(frm) {
        distribute_incentive(frm);
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


    let tt = (row.price_list_rate_copy+row.base_shipping+row.base_processing_charges+row.base_reward+row.base_levee+row.base_std_margin)
    let duty = flt(row.price_list_rate_copy) * flt(row.custom_duty) / 100;
    let plc = frm.doc.plc_conversion_rate
    let conv = frm.doc.conversion_rate

    setTimeout(() => {
        // if (!frm.doc.amended_from){
        frappe.model.set_value(row.doctype,row.name, 'base_price_list_rate',row.usd_price_list_rate_with_margin*plc*conv)
        frappe.model.set_value(row.doctype,row.name, 'custom_duty_charges',duty)
        let price_list_currency = cur_frm.doc.price_list_currency;
        let customer_currency = cur_frm.doc.currency;
        let price_list_exchange_rate = cur_frm.doc.plc_conversion_rate || 1; // Price List Exchange Rate
        console.log("Price List rate copy: ",row.price_list_rate_copy)
        frappe.db.get_value("Item Price", {"item_code": row.item_code,"price_list":frm.doc.selling_price_list}, "custom_standard_price", (d) => {
            if (customer_currency === price_list_currency) {
            // No conversion needed
                frappe.model.set_value(row.doctype, row.name, 'custom_standard_price_', d.custom_standard_price);
                frappe.model.set_value(row.doctype, row.name, 'custom_special_price', d.custom_standard_price);
                // if (!row.custom_special_price || row.custom_special_price == row.price_list_rate) {
                //     frappe.model.set_value(row.doctype, row.name, 'custom_special_price', d.custom_standard_price);
                // }
            } else {
                // Convert using Price List Exchange Rate
                // let converted_price = row.price_list_rate * price_list_exchange_rate;
                // console.log(row.price_list_rate_copy)
                let standard_price_copy = d.custom_standard_price * price_list_exchange_rate;
                frappe.model.set_value(row.doctype, row.name, 'custom_standard_price_', standard_price_copy);
                frappe.model.set_value(row.doctype, row.name, 'custom_special_price', standard_price_copy);
                // if (!row.custom_special_price || row.custom_special_price == price_list_rate_copy) {
                //     frappe.model.set_value(row.doctype, row.name, 'custom_special_price', standard_price_copy);
                // }
            }
        
        })
        

        // frappe.model.set_value(row.doctype,row.name,'custom_standard_price_',row.price_list_rate)
        // frappe.model.set_value(row.doctype,row.name,'custom_special_price',row.price_list_rate)
        
    },100)

    setTimeout(() => {
        // if (!frm.doc.amended_from){
            // frappe.model.set_value(row.doctype,row.name, 'price_list_rate',(row.usd_price_list_rate_with_margin*plc*conv))

        },100)
        
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


}

frappe.db.get_value(
    "Brand",
    { brand: row.brand },
    [
        "shipping",
        "processing_charges",
        "reward",
        "levee",
        "std_margin",
        "custom_finance_",
        "custom_transport"
    ],
    (b) => {
        if (!b) return;

        console.log("Brand values:", b);

        frappe.db.get_list("Item Price", {
            filters: {
                item_code: row.item_code,
                price_list: frm.doc.selling_price_list,
                
            },
            fields: [
                "name",
                "custom_shipping__air_",
                "custom_shipping__sea_",
                "custom_processing_",
                "custom_min_finance_charge_",
                "custom_min_margin_",
                "custom_customs_",
                "custom_gst__vat_"  

            ],
            limit: 1
        }).then((res) => {

            if (!res || !res.length) {
                console.log(
                    "No Price List found for",
                    "Price List:", row.selling_price_list,
                    "Item:", row.item_code
                );
                return;
            }

            const p = res[0];

            // 🔍 DEBUG LOGS
            console.log("Matched Price List row:", p);
            console.log("Shipping Air %:", p.custom_shipping__air_);
            console.log("Shipping Sea %:", p.custom_shipping__sea_);
            console.log("Processing %:", p.custom_processing_);
            console.log("Min Finance Charge %:", p.custom_min_finance_charge_);
            console.log("Min Margin %:", p.custom_min_margin_);
            console.log("Customs %:", p.custom_customs_);
            console.log("GST / VAT %:", p.custom_gst__vat_);

            // ─────────────────────────────────────
            // SET VALUES IN QUOTATION ITEM ROW
            // ─────────────────────────────────────

            if (!row.shipping_per) {
                frappe.model.set_value(
                    row.doctype,
                    row.name,
                    "shipping_per",
                    p.custom_shipping__air_
                );
            }

            if (!row.processing_charges_per) {
                frappe.model.set_value(
                    row.doctype,
                    row.name,
                    "processing_charges_per",
                    p.custom_processing_
                );
            }

            if (!row.std_margin_per) {
                frappe.model.set_value(
                    row.doctype,
                    row.name,
                    "std_margin_per",
                    p.custom_min_margin_
                );
            }

            if (!row.custom_finance_) {
                frappe.model.set_value(
                    row.doctype,
                    row.name,
                    "custom_finance_",
                    p.custom_min_finance_charge_
                );
            }

            if (!row.custom_customs_) {
                frappe.model.set_value(
                    row.doctype,
                    row.name,
                    "custom_customs_",
                    p.custom_customs_
                );
            }

            update_rates(frm, cdt, cdn);
        });

    }
);


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
    let markup_base = base_amount + incentive;
    let markup = markup_per * markup_base / 100;
    let total = markup_base + markup;

    let customs = customs_per * total / 100;
    let cogs = base_amount + incentive + customs;
    let selling_price = total + customs;

    let margin_percent = total !== 0 ? (markup / selling_price) * 100 : 0;
    let margin_value = (margin_percent / 100) * selling_price;

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
        if (!brand) return;

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
                buying_price: 0,
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
        let buying_price = sp * qty;
        let shipping = ((flt(row.shipping_per) * std_price) / 100) * qty;
        let finance = ((flt(row.custom_finance_) * sp) / 100) * qty;
        let transport = ((flt(row.custom_transport_) * std_price) / 100) * qty;
        let reward = ((flt(row.reward_per) * sp) / 100) * qty;

        let base_amount = (sp * qty) + shipping + finance + transport + reward;

        let incentive_percent = flt(row.custom_incentive_);
        let incentive = (base_amount * incentive_percent / 100);

        let markup_base = base_amount + incentive;
        let markup = (flt(row.custom_markup_) * markup_base / 100);

        let total = markup_base + markup;

        let customs_percent = flt(row.custom_customs_);
        let customs = (customs_percent * total / 100);

        // let cogs = base_amount + incentive + customs;
        let selling_price = flt(row.custom_selling_price);

        // cost already correct
        let cogs = flt(row.custom_cogs);

        // recompute margin correctly
        let margin = selling_price - cogs;
        if (margin < 0) margin = 0;

        // row-level margin % (optional, not accumulated)
        let margin_percent =
            selling_price ? (margin / selling_price) * 100 : 0;

        // ───────────── Accumulate Brand Data ─────────────
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
        brand_data[brand].buying_price += buying_price;
        brand_data[brand].total_cost += cogs;
        brand_data[brand].total_selling += selling_price;
        brand_data[brand].margin += margin;
        brand_data[brand].margin_percent += margin_percent;
        brand_data[brand].item_count += 1;
    });

    // ───────────── Clear Table ─────────────
    frm.clear_table('custom_quotation_brand_summary');

    let total_summary = {
        shipping: 0,
        finance: 0,
        transport: 0,
        reward: 0,
        incentive: 0,
        margin: 0,
        customs: 0,
        buying_price: 0,
        total_cost: 0,
        total_selling: 0,
        count: 0
    };

    // ───────────── Brand Summary Rows ─────────────
    Object.keys(brand_data).forEach(brand => {
        let data = brand_data[brand];
        let count = data.item_count || 1;

        let brand_margin_percent =
            data.total_selling
                ? ((data.total_selling - data.total_cost) / data.total_selling) * 100
                : 0;

        frm.add_child('custom_quotation_brand_summary', {
            brand: brand,
            buying_price: data.buying_price,
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
            margin_percent: brand_margin_percent
        });

        total_summary.shipping += data.shipping;
        total_summary.finance += data.finance;
        total_summary.transport += data.transport;
        total_summary.reward += data.reward;
        total_summary.incentive += data.incentive;
        total_summary.margin += data.margin;
        total_summary.customs += data.customs;
        total_summary.total_cost += data.total_cost;
        total_summary.buying_price += data.buying_price;
        total_summary.total_selling += data.total_selling;
        total_summary.count += count;
    });

    frm.refresh_field('custom_quotation_brand_summary');

    // ───────────── Total Margin % (CORRECT) ─────────────
    let total_margin_percent =
        total_summary.total_selling
            ? ((total_summary.total_selling - total_summary.total_cost)
              / total_summary.total_selling) * 100
            : 0;

    // ───────────── Set Form Totals ─────────────
    frm.set_value('custom_total_shipping_new', total_summary.shipping);
    frm.set_value('custom_total_finance_new', total_summary.finance);
    frm.set_value('custom_total_transport_new', total_summary.transport);
    frm.set_value('custom_total_reward_new', total_summary.reward);
    frm.set_value('custom_total_incentive_new', total_summary.incentive);
    frm.set_value('custom_total_customs_new', total_summary.customs);
    frm.set_value('custom_total_margin_new', total_summary.margin);
    frm.set_value('custom_total_cost_new', total_summary.total_cost);
    frm.set_value('custom_total_buying_price', total_summary.buying_price);
    frm.set_value('custom_total_selling_new', total_summary.total_selling);
    frm.set_value('custom_total_margin_percent_new', total_margin_percent);

    console.log("✅ Brand summary and TOTAL margin % updated correctly.");
}

function calculate_custom_rate(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    if (row.qty > 0) {
        let special_rate = row.custom_selling_price / row.qty;
        let net_selling_rate = row.custom_net_selling_price / row.qty;
        frappe.model.set_value(cdt, cdn, 'custom_special_rate', special_rate);
        if (flt(row.custom_net_selling_price) > 0) {
            frappe.model.set_value(cdt, cdn, 'rate', net_selling_rate);
        } else {
            frappe.model.set_value(cdt, cdn, 'rate', special_rate);
        }
    }
}

function handle_qty_or_rate_change(frm, cdt, cdn) {
    let row = locals[cdt][cdn];

    // Check if the row belongs to your second table (not main 'items')
    if (row.parentfield === 'custom_service_items') {
        calculate_custom_amount(frm, row);
        frm.refresh_field('custom_service_items');
    }
}

function calculate_custom_amount(frm, row) {
    const qty = flt(row.qty);
    const rate = flt(row.rate);

    row.amount = qty * rate;
    // frm.refresh_field("custom_service_items");
    // row.base_rate = rate;
    // row.base_amount = row.amount;
    // row.net_amount = row.amount;

    // If needed, calculate other fields like discounts here
}

function update_custom_service_totals(frm) {
    let total_qty = 0;
    let total_amount = 0;

    (frm.doc.custom_service_items || []).forEach(row => {
        total_qty += flt(row.qty);
        total_amount += flt(row.amount);
    });

    frm.set_value('custom_total_qty', total_qty);
    frm.set_value('custom_total', total_amount);

    // If conversion_rate exists (e.g. from quotation), use it
    let conversion_rate = flt(frm.doc.conversion_rate || 1);
    frm.set_value('custom_total_company_currency', total_amount * conversion_rate);
}

function sync_shipment_margin_percent(frm, cdt, cdn) {
    let item_row = locals[cdt][cdn];

    if (!item_row || item_row.custom_margin_ == null) return;

    // Shipment table must have a row
    if (!frm.doc.custom_shipment_and_margin ||
        !frm.doc.custom_shipment_and_margin.length) {
        return;
    }

    // As per your UI, only ONE row exists
    let ship_row = frm.doc.custom_shipment_and_margin[0];

    frappe.model.set_value(
        ship_row.doctype,
        ship_row.name,
        "margin",
        item_row.custom_margin_
    );
}
function update_items_shipping_percent(frm) {

    if (!frm.doc.items || !frm.doc.items.length) return;
    if (!frm.doc.custom_shipment_and_margin ||
        !frm.doc.custom_shipment_and_margin.length) return;

    const ship_row = frm.doc.custom_shipment_and_margin[0];
    const mode = frm.doc.custom_shipping_mode;

    let shipping_percent = 0;

    if (mode === "Air") {
        shipping_percent = ship_row.ship_air || 0;
    } else if (mode === "Sea") {
        shipping_percent = ship_row.ship_sea || 0;
    }

    frm.doc.items.forEach(item => {
        frappe.model.set_value(
            item.doctype,
            item.name,
            "shipping_per",
            shipping_percent
        );
    });
}
function normalize_incentive_percent(frm, source) {

    let total_cost = 0;
    frm.doc.items.forEach(row => {
        total_cost += flt(row.custom_cogs) * flt(row.qty);
    });

    if (!total_cost) return;

    // 🔹 BOTH EMPTY → reset
    if (!flt(frm.doc.custom_incentive_) &&
        !flt(frm.doc.custom_incentive_amount)) {

        frm.set_value("custom_incentive_", 0);
        frm.set_value("custom_incentive_amount", 0);
        return;
    }

    // 🔹 USER EDITED PERCENT → calculate AMOUNT
    if (source === "percent") {
        let amount = (total_cost * flt(frm.doc.custom_incentive_)) / 100;
        frm.set_value("custom_incentive_amount", amount);
        return;
    }

    // 🔹 USER EDITED AMOUNT → calculate PERCENT
    if (source === "amount") {
        let percent =
            (flt(frm.doc.custom_incentive_amount) / total_cost) * 100;
        frm.set_value("custom_incentive_", percent);
        return;
    }
}


function distribute_incentive(frm) {
    if (frm.__distributing_incentive) return;
    frm.__distributing_incentive = true;

    if (!frm.doc.items || !frm.doc.items.length) {
        frm.__distributing_incentive = false;
        return;
    }

    if (frm.doc.custom_distribute_incentive_based_on === "Distributed Manually") {
        frm.__distributing_incentive = false;
        return;
    }

    let total_cost = 0;
    frm.doc.items.forEach(row => {
        total_cost += flt(row.custom_cogs) * flt(row.qty);
    });

    if (!total_cost) {
        frm.__distributing_incentive = false;
        return;
    }

    let total_incentive_amount = flt(frm.doc.custom_incentive_amount);
    if (!total_incentive_amount) {
        frm.__distributing_incentive = false;
        return;
    }

    frm.doc.items.forEach(row => {

        let qty = flt(row.qty) || 1;
        let cogs = flt(row.custom_cogs);
        let markup = flt(row.custom_markup_) || 0;

        let row_cost = cogs * qty;
        let row_incentive = 0;

        // 🔹 Incentive distribution
        if (frm.doc.custom_distribute_incentive_based_on === "Distributed Equally") {
            row_incentive = total_incentive_amount / frm.doc.items.length;
        }
        else if (frm.doc.custom_distribute_incentive_based_on === "Amount") {
            row_incentive = (row_cost / total_cost) * total_incentive_amount;
        }

        // 🔹 Per-unit incentive (VERY IMPORTANT)
        let incentive_per_unit = row_incentive / qty;

        // 🔹 Adjusted cost per unit
        let adjusted_cost = cogs + incentive_per_unit;

        // 🔹 Customer special price (markup only once)
        let custom_special_price =
            adjusted_cost + (adjusted_cost * markup / 100);

        // 🔹 Row values
        row.custom_incentive_value = row_incentive;
        row.custom_incentive_ = row_cost
            ? (row_incentive / row_cost) * 100
            : 0;

        row.custom_special_rate = custom_special_price;
        row.custom_selling_price = custom_special_price * qty;
        row.rate = custom_special_price;
        row.amount = custom_special_price * qty;

        // 🔹 RO fields
        row.roDate = frappe.datetime.nowdate();
        row.roAmount = row_incentive;

        // 🔹 Margin (clean & correct)
        let margin_value = (custom_special_price - cogs) * qty;
        let margin_percent = custom_special_price
            ? ((custom_special_price - cogs) / custom_special_price) * 100
            : 0;

        row.custom_margin_value = margin_value;
        row.custom_margin_ = margin_percent;
    });

    frm.refresh_field("items");
    frm.trigger("calculate_taxes_and_totals");
    frm.__distributing_incentive = false;
}



frappe.ui.form.on('Quotation Item',{
item_code:function(frm, cdt,cdn){
        var row = locals[cdt][cdn]
        if (!frm.doc.party_name) {
            frappe.msgprint(__('Customer must be selected before choosing an item.'));
            return;
        }
        if (!row.item_code || !frm.doc.party_name) {
            return;
        }
        
        // 1️⃣ Clear previous item data
        frm.clear_table("custom_history");
        frm.clear_table("custom_stock");
        frm.clear_table("custom_shipment_and_margin");
        frm.refresh_fields(["custom_history", "custom_stock", "custom_shipment_and_margin"]);

        // 2️⃣ Call server
        frappe.call({
            method: "avientek.events.quotation.get_item_all_details",
            args: {
                item_code: row.item_code,
                customer: frm.doc.party_name,
                price_list: frm.doc.selling_price_list
            },
            callback: function (r) {
                if (!r.message) return;

                // -----------------------
                // CUSTOMER HISTORY
                // -----------------------
                (r.message.history || []).forEach(d => {
                    let h = frm.add_child("custom_history");
                    h.document_type = d.doctype;
                    h.document_id = d.name;
                    h.qty = d.qty;
                    h.unit_price = d.rate;
                });

                // -----------------------
                // COMPANY STOCK
                // -----------------------
                (r.message.stock || []).forEach(s => {
                    let st = frm.add_child("custom_stock");
                    st.company = s.company;
                    st.actual_stock = s.actual_stock;
                    st.free_stock = s.free_stock;
                    st.projected_stock = s.projected_stock;
                });
                if (r.message.shipment_margin) {
                    let sm = frm.add_child("custom_shipment_and_margin");
                    sm.ship_air = r.message.shipment_margin.ship_air;
                    sm.ship_sea = r.message.shipment_margin.ship_sea;
                    sm.std_margin = r.message.shipment_margin.std_margin;
                    // margin_percent → calculated later
                }

                frm.refresh_fields(["custom_history", "custom_stock"]);
            }

        });
    setTimeout(() => {
        var row = locals[cdt][cdn]
        frappe.db.get_value("Item Price", {"item_code": row.item_code,"price_list":frm.doc.selling_price_list}, "custom_standard_price", (d) => {
            // console.log("custom duty",d.price_list_rate)
            if(d.custom_standard_price){
                frappe.model.set_value(row.doctype,row.name,'usd_price_list_rate',d.custom_standard_price)
                frappe.model.set_value(row.doctype,row.name,'usd_price_list_rate_with_margin',d.custom_standard_price)
                

            }
        });
        // if(row.brand && row.base_price_list_rate){
        //     console.log("item",row.item_code)
        //     frappe.model.set_value(row.doctype,row.name,'price_list_rate_copy',row.base_price_list_rate)
        // }
        rate_calculation(frm,cdt,cdn)
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
        }
        // handle_qty_or_rate_change(frm, cdt, cdn);
       
    },1000)
},


usd_price_list_rate_with_margin:function(frm,cdt,cdn) {
    var row = locals[cdt][cdn]
    if(row.usd_price_list_rate_with_margin){
        let plc = frm.doc.plc_conversion_rate
        let conv = frm.doc.conversion_rate
       
        if(!frm.doc.plc_conversion_rate || (frm.doc.currency == frm.doc.price_list_currency)){
            plc = 1
        }
        if(!frm.doc.conversion_rate){
            conv =1
        }

        frappe.model.set_value(row.doctype,row.name,'price_list_rate_copy',(row.usd_price_list_rate_with_margin*plc*conv))
      
    }
},
price_list_rate_copy:function(frm,cdt,cdn){
    var row = locals[cdt][cdn]
    if(row.brand && row.price_list_rate_copy){
        row.std_margin = (flt(row.price_list_rate_copy) * flt(row.std_margin_per) / 100)/ frm.doc.conversion_rate;
        // row.base_std_margin = row.std_margin*frm.doc.conversion_rate;
    }
    update_rates(frm,cdt,cdn)
},

custom_special_price:function(frm,cdt,cdn){
    calculate_all(frm, cdt, cdn);
    calculate_custom_rate(frm, cdt, cdn);
    var row = locals[cdt][cdn]
    if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
    }
},

reward_per:function(frm, cdt,cdn){
    calculate_all(frm, cdt, cdn);
    calculate_custom_rate(frm, cdt, cdn);
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
        
    }

},

custom_incentive_(frm, cdt, cdn) {
    calculate_all(frm, cdt, cdn);
    calculate_custom_rate(frm, cdt, cdn);
    var row = locals[cdt][cdn]

    if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
    }
},
custom_markup_(frm,cdt,cdn){
    // console.log("Markup : ",markup )
    calculate_all(frm, cdt, cdn);
    calculate_custom_rate(frm, cdt, cdn);
    var row = locals[cdt][cdn]
    if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
    }
    sync_shipment_margin_percent(frm, cdt, cdn);
},
custom_customs_(frm,cdt,cdn){
    calculate_all(frm, cdt, cdn);
    calculate_custom_rate(frm, cdt, cdn);
    var row = locals[cdt][cdn]
    if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
    }
    // var row = locals[cdt][cdn]
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
amount(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.parentfield === 'custom_service_items') {
            update_custom_service_totals(frm);
        }
    },

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
        if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
        }

    // }

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
    calculate_all(frm, cdt, cdn);
    var row = locals[cdt][cdn]
    if(row.brand && row.price_list_rate_copy){
        // if (row.std_margin_per) {
            row.std_margin = (flt(row.price_list_rate_copy) * flt(row.std_margin_per) / 100)/ frm.doc.conversion_rate;
            row.base_std_margin = row.std_margin*frm.doc.conversion_rate;
        // }
        update_rates(frm,cdt,cdn)
    }

},
custom_margin_:function(frm, cdt,cdn){
    sync_shipment_margin_percent(frm, cdt, cdn);
},

qty:function(frm, cdt,cdn){
    calculate_all(frm, cdt, cdn);
    calculate_custom_rate(frm, cdt, cdn);
    var row = locals[cdt][cdn]
    if (row.parentfield === 'custom_service_items') {
            handle_qty_or_rate_change(frm, cdt, cdn);
            update_custom_service_totals(frm);
    }
},
// custom_discount_amount_qty: function(frm, cdt, cdn) {

//     // 🔴 IMPORTANT: skip if bulk discount is running
//     if (frm.custom_applying_bulk_discount) {
//         return;
//     }

//     let row = locals[cdt][cdn];

//     let discount_amount = flt(row.custom_discount_amount_qty);
//     let qty = flt(row.qty);
//     if (!discount_amount || qty <= 0) return;

//     let per_unit_discount = discount_amount / qty;
//     let unit_price = flt(row.custom_special_rate || row.rate);

//     let new_unit_price = unit_price - per_unit_discount;
//     if (new_unit_price < 0) new_unit_price = 0;

//     let new_selling_amount = new_unit_price * qty;

//     let old_margin_val = flt(row.custom_margin_value || 0);
//     let new_margin_val = old_margin_val - discount_amount;
//     if (new_margin_val < 0) new_margin_val = 0;

//     let new_margin_pct = new_selling_amount > 0
//         ? (new_margin_val / new_selling_amount) * 100
//         : 0;

//     frappe.model.set_value(cdt, cdn, "custom_special_rate", new_unit_price);
//     frappe.model.set_value(cdt, cdn, "custom_selling_price", new_selling_amount);
//     frappe.model.set_value(cdt, cdn, "custom_margin_value", new_margin_val);
//     frappe.model.set_value(cdt, cdn, "custom_margin_", new_margin_pct);
//     frappe.model.set_value(cdt, cdn, "rate", new_unit_price);
//     frappe.model.set_value(cdt, cdn, "amount", new_selling_amount);
//     frappe.model.set_value(cdt, cdn, "custom_discount_amount_value", per_unit_discount);
// },


custom_service_items_remove: function(frm, cdt, cdn) {
    update_custom_service_totals(frm);
},
before_save:function(frm,cdt,cdn){
    frm.trigger('calculate_total')
},
items_remove:function(frm){
    frm.trigger('calculate_total')
},

})



frappe.ui.form.on('Quotation',{
before_save:function(frm){
    frm.trigger('calculate_total')
},

refresh:function(frm){ 
    update_custom_service_totals(frm);
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
    
},
onload:function(frm){
    frm.set_query('custom_quote_project', function() {
            return {
                query: 'avientek.events.sales_person_permission.get_project_quotation_for_user'
            };
        });
    var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
    // frm.set_currency_labels([
    //     "base_shipping","base_processing_charges","base_reward","base_levee","base_std_margin","base_total_shipping","base_total_processing_charges","base_total_reward","base_total_levee","base_total_std_margin"
    // ], company_currency, "items");
    // frm.set_currency_labels([
    //     "base_total_shipping","base_total_processing_charges","base_total_reward","base_total_levee","base_total_std_margin"
    // ], company_currency);

    // var trans_currency = frm.doc.currency
    // frm.set_currency_labels([
    //     "shipping","processing_charges","reward","levee","std_margin","total_shipping","total_processing_charges","total_reward","total_levee","total_std_margin"
    // ], trans_currency, "items");
    // frm.set_currency_labels([
    //     "total_shipping","total_processing_charges","total_reward","total_levee","total_std_margin"
    // ], trans_currency);
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

        // if (doc.items[i].base_total_shipping){
        //     base_shipping_total += doc.items[i].base_total_shipping;
        // }       
        // if (doc.items[i].base_processing_charges){
        //     base_pc_total += doc.items[i].base_processing_charges;
        // }       
        // if (doc.items[i].base_reward){
        //     base_reward_total += doc.items[i].base_reward;
        // }       
        // if (doc.items[i].base_levee){
        //     base_levee_total += doc.items[i].base_levee;
        // }       
        // if (doc.items[i].base_std_margin){
        //     base_std_total += doc.items[i].base_std_margin;
        // }       
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