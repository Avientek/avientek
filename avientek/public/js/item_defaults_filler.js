/**
 * Fills mandatory item_name / uom / stock_uom / description / conversion_factor
 * when only item_code is populated on a transaction row.
 *
 * CSV/Excel upload into the items grid sets cells in CSV column order. If the
 * template has an "Item Name" column with a blank cell, Frappe will call
 * set_value("item_name", "") AFTER the item_code trigger fires — that
 * overwrites whatever our async Item-master fetch set. Hooking only
 * item_code therefore loses the race on bulk upload.
 *
 * The fix is two-layered: (1) hook the child-doctype item_code change for
 * manual entry, (2) sweep every row on every parent form refresh so any
 * row that ended up with item_code but missing item_name/uom gets filled
 * after the upload finishes. The sweep is delayed and debounced so it
 * runs once after the upload's cascade of set_value calls settles.
 */
(function () {
    const PARENT_TO_TABLE = {
        "Quotation": "items",
        "Sales Order": "items",
        "Delivery Note": "items",
        "Sales Invoice": "items",
        "Purchase Order": "items",
        "Purchase Invoice": "items",
        "Purchase Receipt": "items",
    };

    const item_cache = {};           // item_code -> {item_name, stock_uom, description}
    const pending = new Set();       // item_codes currently being fetched
    const sweep_timers = new WeakMap();

    function apply(cdt, cdn, data) {
        const row = locals[cdt] && locals[cdt][cdn];
        if (!row) return;
        if (!row.item_name && data.item_name) {
            frappe.model.set_value(cdt, cdn, "item_name", data.item_name);
        }
        if (!row.uom && data.stock_uom) {
            frappe.model.set_value(cdt, cdn, "uom", data.stock_uom);
        }
        if (!row.stock_uom && data.stock_uom) {
            frappe.model.set_value(cdt, cdn, "stock_uom", data.stock_uom);
        }
        if (!row.description && (data.description || data.item_name)) {
            frappe.model.set_value(cdt, cdn, "description", data.description || data.item_name);
        }
        if (!row.conversion_factor) {
            frappe.model.set_value(cdt, cdn, "conversion_factor", 1);
        }
    }

    function fetch_and_apply(cdt, cdn) {
        const row = locals[cdt] && locals[cdt][cdn];
        if (!row || !row.item_code) return;
        if (row.item_name && row.uom) return;

        const code = row.item_code;
        if (item_cache[code]) { apply(cdt, cdn, item_cache[code]); return; }
        if (pending.has(code)) { return; }

        pending.add(code);
        frappe.db.get_value("Item", code, ["item_name", "stock_uom", "description"])
            .then(function (r) {
                pending.delete(code);
                const d = (r && r.message) || {};
                if (d.item_name) item_cache[code] = d;
                apply(cdt, cdn, d);
            })
            .catch(function () { pending.delete(code); });
    }

    function sweep(frm, tablefield) {
        (frm.doc[tablefield] || []).forEach(function (row) {
            if (row.item_code && (!row.item_name || !row.uom)) {
                fetch_and_apply(row.doctype, row.name);
            }
        });
    }

    function schedule_sweep(frm, tablefield) {
        if (sweep_timers.has(frm)) clearTimeout(sweep_timers.get(frm));
        const timer = setTimeout(function () {
            sweep_timers.delete(frm);
            sweep(frm, tablefield);
        }, 600);
        sweep_timers.set(frm, timer);
    }

    Object.keys(PARENT_TO_TABLE).forEach(function (parent_dt) {
        const tablefield = PARENT_TO_TABLE[parent_dt];
        const child_dt = parent_dt + " Item";

        frappe.ui.form.on(child_dt, {
            item_code: function (frm, cdt, cdn) {
                fetch_and_apply(cdt, cdn);
                setTimeout(function () { fetch_and_apply(cdt, cdn); }, 400);
            },
        });

        frappe.ui.form.on(parent_dt, {
            refresh: function (frm) { schedule_sweep(frm, tablefield); },
            items_on_form_rendered: function (frm) { schedule_sweep(frm, tablefield); },
        });
    });
})();
