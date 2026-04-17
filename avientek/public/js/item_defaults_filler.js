/**
 * Fills mandatory item_name / uom / stock_uom / description / conversion_factor
 * when only item_code is populated on a transaction row.
 *
 * THREE layers of coverage so nothing slips through:
 *   1. Child item_code change hook — manual row entry, fires immediately.
 *   2. Parent refresh + items_on_form_rendered — debounced sweep catches
 *      CSV/Excel upload where item_code fires but a later empty
 *      set_value("item_name", "") from a blank CSV cell overwrites our
 *      async fetch result.
 *   3. Parent `validate` hook — returns a Promise that blocks the save
 *      until any missing item_name/uom are filled. This is the backstop
 *      for users who hit Save before the debounced sweep fires. Frappe
 *      awaits a Promise-returning validate before the client-side
 *      mandatory check runs.
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

    const item_cache = {};
    const pending = new Set();
    const sweep_timers = new WeakMap();

    function apply(cdt, cdn, data) {
        const row = locals[cdt] && locals[cdt][cdn];
        if (!row) return;
        const p = [];
        if (!row.item_name && data.item_name) {
            p.push(frappe.model.set_value(cdt, cdn, "item_name", data.item_name));
        }
        if (!row.uom && data.stock_uom) {
            p.push(frappe.model.set_value(cdt, cdn, "uom", data.stock_uom));
        }
        if (!row.stock_uom && data.stock_uom) {
            p.push(frappe.model.set_value(cdt, cdn, "stock_uom", data.stock_uom));
        }
        if (!row.description && (data.description || data.item_name)) {
            p.push(frappe.model.set_value(cdt, cdn, "description", data.description || data.item_name));
        }
        if (!row.conversion_factor) {
            p.push(frappe.model.set_value(cdt, cdn, "conversion_factor", 1));
        }
        return Promise.all(p);
    }

    function fetch_item(code) {
        if (item_cache[code]) return Promise.resolve(item_cache[code]);
        return frappe.db.get_value("Item", code, ["item_name", "stock_uom", "description"])
            .then(function (r) {
                const d = (r && r.message) || {};
                if (d.item_name) item_cache[code] = d;
                return d;
            })
            .catch(function () { return {}; });
    }

    function fetch_and_apply(cdt, cdn) {
        const row = locals[cdt] && locals[cdt][cdn];
        if (!row || !row.item_code) return Promise.resolve();
        if (row.item_name && row.uom) return Promise.resolve();
        const code = row.item_code;
        if (pending.has(code + ":" + cdn)) return Promise.resolve();
        pending.add(code + ":" + cdn);
        return fetch_item(code)
            .then(function (data) {
                pending.delete(code + ":" + cdn);
                return apply(cdt, cdn, data);
            })
            .catch(function () { pending.delete(code + ":" + cdn); });
    }

    function sweep_grid(frm, tablefield) {
        const promises = [];
        (frm.doc[tablefield] || []).forEach(function (row) {
            if (row.item_code && (!row.item_name || !row.uom)) {
                promises.push(fetch_and_apply(row.doctype, row.name));
            }
        });
        return Promise.all(promises);
    }

    function schedule_sweep(frm, tablefield) {
        if (sweep_timers.has(frm)) clearTimeout(sweep_timers.get(frm));
        const timer = setTimeout(function () {
            sweep_timers.delete(frm);
            sweep_grid(frm, tablefield);
        }, 500);
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
            // THE BACKSTOP: Frappe awaits a Promise-returning validate before
            // running the client-side mandatory-field check. So we fill every
            // missing item_name/uom synchronously (as far as the save flow
            // is concerned) right before the Missing-Fields dialog would fire.
            validate: function (frm) {
                return sweep_grid(frm, tablefield);
            },
        });
    });
})();
