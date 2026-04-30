// Copyright (c) 2026, Avientek and contributors
// For license information, please see license.txt

frappe.ui.form.on('Sales Person Target', {
    refresh(frm) {
        // Submitted form is read-only — show a "Copy from Previous Year"
        // button that creates a NEW draft for next fiscal year. Button
        // appears on draft form too so users can pre-populate from any
        // submitted source.
        if (!frm.doc.__islocal) {
            frm.add_custom_button(__('Copy to New Fiscal Year'), function () {
                _prompt_copy(frm);
            });
        }
    },

    onload(frm) {
        // For a brand-new doc, offer to pre-populate from the previous
        // year's target the moment Sales Person + Fiscal Year are set.
        if (frm.is_new()) {
            // Run after the user fills both fields (handled by their respective
            // change events below).
        }
    },

    sales_person(frm) {
        _maybe_offer_copy(frm);
    },

    fiscal_year(frm) {
        _maybe_offer_copy(frm);
    },
});

function _maybe_offer_copy(frm) {
    if (!frm.is_new()) return;
    if (!frm.doc.sales_person || !frm.doc.fiscal_year) return;
    if (frm._spt_offered_copy) return;
    if ((frm.doc.targets || []).length > 0) return;

    // Check if a previous submitted SPT exists for this sales person.
    frappe.db.get_list('Sales Person Target', {
        filters: { sales_person: frm.doc.sales_person, docstatus: 1 },
        fields: ['name', 'fiscal_year'],
        order_by: 'modified desc',
        limit: 1,
    }).then((rows) => {
        if (!rows || !rows.length) return;
        if (rows[0].fiscal_year === frm.doc.fiscal_year) return;
        frm._spt_offered_copy = true;
        frappe.confirm(
            __('A previous submitted target exists for {0} ({1}). Copy its rows into this new target for {2}?',
                [frm.doc.sales_person, rows[0].fiscal_year, frm.doc.fiscal_year]),
            function () {
                _do_copy(frm, rows[0].fiscal_year);
            }
        );
    });
}

function _prompt_copy(frm) {
    frappe.prompt(
        [
            {
                fieldname: 'fiscal_year',
                label: __('New Fiscal Year'),
                fieldtype: 'Link',
                options: 'Fiscal Year',
                reqd: 1,
            },
        ],
        function (vals) {
            frappe.call({
                method: 'avientek.avientek.doctype.sales_person_target.sales_person_target.copy_from_previous_year',
                args: {
                    sales_person: frm.doc.sales_person,
                    fiscal_year: vals.fiscal_year,
                    source_fiscal_year: frm.doc.fiscal_year,
                },
                freeze: true,
                freeze_message: __('Copying targets…'),
                callback: function (r) {
                    if (r && r.message) {
                        frappe.set_route('Form', 'Sales Person Target', r.message);
                    }
                },
            });
        },
        __('Copy Targets to New Fiscal Year'),
        __('Copy')
    );
}

function _do_copy(frm, source_fiscal_year) {
    frappe.call({
        method: 'avientek.avientek.doctype.sales_person_target.sales_person_target.copy_from_previous_year',
        args: {
            sales_person: frm.doc.sales_person,
            fiscal_year: frm.doc.fiscal_year,
            source_fiscal_year: source_fiscal_year,
        },
        freeze: true,
        freeze_message: __('Copying targets…'),
        callback: function (r) {
            if (r && r.message) {
                frappe.set_route('Form', 'Sales Person Target', r.message);
            }
        },
    });
}
