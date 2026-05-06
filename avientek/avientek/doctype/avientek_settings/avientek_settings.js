// Copyright (c) 2026, Avientek and contributors
// For license information, please see license.txt

// Avientek Settings — filter the Reward / Incentive account links in
// the Company Account Mapping child table by the row's company. Without
// this, the Account dropdown shows accounts from every company on the
// site and an accountant could accidentally pick a wrong-company GL.

frappe.ui.form.on('Avientek Settings', {
    setup(frm) {
        // Defensive: only register the set_query if the parent grid
        // field exists. When a sibling field's child doctype isn't
        // yet synced (e.g. right after pulling new code, before bench
        // migrate), the meta load can leave fields_dict[parent]
        // undefined and Frappe's set_query throws "Cannot read
        // properties of undefined (reading 'grid')", blanking the
        // entire form.
        if (!frm.fields_dict.reward_incentive_company_accounts) {
            return;
        }
        const acct_fields = [
            'reward_expense_account',
            'reward_payable_account',
            'incentive_expense_account',
            'incentive_payable_account',
        ];
        for (const fn of acct_fields) {
            frm.set_query(fn, 'reward_incentive_company_accounts', function (doc, cdt, cdn) {
                const row = locals[cdt][cdn];
                // Empty company → empty result set (forces user to pick
                // company first; better than showing every company's GLs).
                return {
                    filters: {
                        company: row.company || '',
                        is_group: 0,
                    }
                };
            });
        }
    }
});

// When the company on a row changes, blank the four account fields so a
// stale wrong-company GL doesn't linger after the user switches company.
frappe.ui.form.on('Avientek Reward Incentive Account', {
    company(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        for (const fn of [
            'reward_expense_account',
            'reward_payable_account',
            'incentive_expense_account',
            'incentive_payable_account',
        ]) {
            if (row[fn]) {
                frappe.model.set_value(cdt, cdn, fn, '');
            }
        }
    }
});
