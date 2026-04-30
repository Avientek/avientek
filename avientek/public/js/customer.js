// Copyright (c) 2026, Avientek and contributors
// For license information, please see license.txt
//
// Customer — Credit Limit row: Total = Insured + Internal
//
// Total Credit Limit (the existing `credit_limit` field) is auto-computed
// as Insured Limit + Internal Limit. The field is set to read_only via
// property setter, so users only edit the two component fields. ERPNext's
// credit-limit check (selling/customer.py:check_credit_limit →
// get_credit_limit) reads `credit_limit` directly, so as long as we keep
// it = sum, the existing block-on-overrun behaviour for SO / SI / DN /
// JV stays intact without any patch to ERPNext.

frappe.ui.form.on('Customer Credit Limit', {
    custom_insured_limit(frm, cdt, cdn) {
        _recompute_total(frm, cdt, cdn);
    },
    custom_internal_limit(frm, cdt, cdn) {
        _recompute_total(frm, cdt, cdn);
    },
});

function _recompute_total(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const total = (parseFloat(row.custom_insured_limit) || 0)
                + (parseFloat(row.custom_internal_limit) || 0);
    frappe.model.set_value(cdt, cdn, 'credit_limit', total);
}
