// Copyright (c) 2026, Avientek and contributors
// For license information, please see license.txt
//
// Project form helpers — client meeting 2026-09-08 (Rahul):
//   1. Budget Amount / Budget Value mirrored into read-only USD columns, at a
//      rate that is FROZEN until a budget figure is re-entered.
//   2. Focused Brands shown read-only, fetched from the Lead the selected
//      customer was converted from.
//
// The arithmetic lives in Python (avientek.events.project) and is re-applied
// on validate; this file only calls it so the user sees the numbers before
// saving instead of after. Nothing here is the source of truth.

frappe.ui.form.on("Project", {
	refresh(frm) {
		avientek_project_rate_hint(frm);
	},

	company(frm) {
		// Company (and therefore company currency) changed — the stored rate
		// now points at the wrong currency pair, so re-rate immediately.
		avientek_project_convert_budget(frm);
	},

	custom_budget_amount(frm) {
		avientek_project_convert_budget(frm);
	},

	custom_budget_value(frm) {
		avientek_project_convert_budget(frm);
	},

	customer(frm) {
		avientek_project_fetch_brands(frm);
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

// Mirror the Lead's Focused Brands onto the form. Read-only and rebuilt whole,
// so it can never drift from the Lead.
function avientek_project_fetch_brands(frm) {
	frm.clear_table("custom_focused_brands");

	if (!frm.doc.customer) {
		frm.refresh_field("custom_focused_brands");
		return;
	}

	frappe.call({
		method: "avientek.events.project.get_lead_brands",
		args: { customer: frm.doc.customer },
		callback(r) {
			const d = r.message || {};
			(d.brands || []).forEach((brand) => {
				frm.add_child("custom_focused_brands", { brand: brand });
			});
			frm.refresh_field("custom_focused_brands");

			if (!d.lead) {
				// Not an error — plenty of customers were keyed in directly.
				// Worth saying once so the empty table isn't read as a bug.
				frm.get_field("custom_focused_brands").set_description(
					__("This customer was not created from a Lead, so there are no Focused Brands to show.")
				);
			} else {
				frm.get_field("custom_focused_brands").set_description(
					__("Fetched from Lead {0}.", [d.lead])
				);
			}
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
