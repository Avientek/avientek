// Copyright (c) 2026, Avientek and contributors
// For license information, please see license.txt
//
// Project form helpers:
//   1. Budget Amount / Budget Value mirrored into read-only USD columns, at a
//      rate that is FROZEN until a budget figure is re-entered.
//      (client meeting 2026-09-08, Rahul)
//   2. The two company-currency budget labels carry the company's currency in
//      brackets, e.g. "Budget Value (AED)", so it is obvious which currency
//      the figure is keyed in. (2026-09-10)
//   3. A Contacts section that works like Customer's: linked contacts listed,
//      plus a "New Contact" button. (2026-09-11)
//
// There is deliberately NO brand logic here: the Focused Brands table is keyed
// in by hand like the Lead's, after the client cancelled the auto-fetch.
//
// The arithmetic lives in Python (avientek.events.project) and is re-applied
// on validate; this file only calls it so the user sees the numbers before
// saving instead of after. Nothing here is the source of truth.

frappe.ui.form.on("Project", {
	refresh(frm) {
		avientek_project_rate_hint(frm);
		avientek_project_currency_labels(frm);
		avientek_project_contacts(frm);
	},

	company(frm) {
		// Company (and therefore company currency) changed — the stored rate
		// now points at the wrong currency pair, so re-rate immediately.
		avientek_project_convert_budget(frm);
		avientek_project_currency_labels(frm);
	},

	custom_budget_amount(frm) {
		avientek_project_convert_budget(frm);
	},

	custom_budget_value(frm) {
		avientek_project_convert_budget(frm);
	},
});

// Re-fetch the exchange rate and recompute both USD columns. Called ONLY from
// the budget/company handlers — that is what makes the rate "frozen" for every
// other kind of edit.
function avientek_project_convert_budget(frm) {
	if (!frm.doc.company) return;

	const amount = flt(frm.doc.custom_budget_amount);
	const value = flt(frm.doc.custom_budget_value);

	if (!amount && !value) {
		frm.set_value("custom_exchange_rate", 0);
		frm.set_value("custom_budget_amount_usd", 0);
		frm.set_value("custom_budget_value_usd", 0);
		return;
	}

	frappe.call({
		method: "avientek.events.project.get_budget_usd_preview",
		args: {
			company: frm.doc.company,
			budget_amount: amount,
			budget_value: value,
		},
		callback(r) {
			const d = r.message;
			if (!d) return;

			if (d.company_currency) {
				frm.set_value("custom_company_currency", d.company_currency);
			}

			if (!d.exchange_rate) {
				// No Currency Exchange record. Say so here rather than letting
				// the user discover it at save time.
				frappe.show_alert({
					message: __("No {0} → USD exchange rate found. The USD budget columns stay blank until one is set up.",
						[d.company_currency || "?"]),
					indicator: "orange",
				}, 7);
				return;
			}

			frm.set_value("custom_exchange_rate", d.exchange_rate);
			frm.set_value("custom_budget_amount_usd", d.budget_amount_usd);
			frm.set_value("custom_budget_value_usd", d.budget_value_usd);
			avientek_project_rate_hint(frm);
		},
	});
}

// Restate the freeze rule next to the rate, including when it was last taken,
// so nobody has to guess whether the USD figure is current.
function avientek_project_rate_hint(frm) {
	const field = frm.get_field("custom_exchange_rate");
	if (!field) return;

	if (!flt(frm.doc.custom_exchange_rate)) {
		field.set_description(
			__("Set automatically when a budget figure is entered.")
		);
		return;
	}

	const ccy = frm.doc.custom_company_currency || __("company currency");
	field.set_description(
		__("1 USD = {0} {1}, frozen. To refresh, re-enter Budget Amount / Budget Value and save.",
			[format_number(frm.doc.custom_exchange_rate, null, 4), ccy])
	);
}

// Show the company's currency in the budget labels — "Budget Amount (AED)" —
// so it is unambiguous which currency the figure is keyed in. The USD twins
// are always USD and keep their static labels.
//
// Read with frappe.db.get_value rather than frm.doc.custom_company_currency:
// that field is stamped server-side on validate, so on a freshly opened or
// brand-new project it is not populated yet. Deliberately does NOT write to
// the doc — setting a value here would mark an untouched form "Not Saved".
function avientek_project_currency_labels(frm) {
	const apply = (ccy) => {
		const suffix = ccy ? ` (${ccy})` : "";
		frm.set_df_property("custom_budget_amount", "label", __("Budget Amount") + suffix);
		frm.set_df_property("custom_budget_value", "label", __("Budget Value") + suffix);
	};

	if (!frm.doc.company) {
		apply(null);
		return;
	}

	frappe.db.get_value("Company", frm.doc.company, "default_currency").then((r) => {
		apply((r.message || {}).default_currency);
	});
}

// The same call Customer's refresh makes. It draws `__onload.contact_list`
// (loaded by avientek.events.project.load_contacts) into the contact_html
// field and wires its "New Contact" button, which opens a new Contact with
// this project already in its Links table. A new project has no contacts and
// nothing to link to yet, so the section is cleared instead.
function avientek_project_contacts(frm) {
	if (frm.is_new()) {
		frappe.contacts.clear_address_and_contact(frm);
	} else {
		frappe.contacts.render_address_and_contact(frm);
	}
}
