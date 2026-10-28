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
//   4. Edit lock on Approved / Closed projects closing within 6 months:
//      read-only form, Request Edit / Allow Edit / Decline buttons.
//      (Rahul 2026-10-13, point 13; rules in avientek.events.project)
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
		avientek_project_edit_lock(frm);
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

	custom_focused_brands_remove(frm) {
		avientek_project_convert_budget(frm);
	},
});

// 2026-09-24: Focused Brands row Value -> Value (USD) at the same frozen rate
// as the Budget USD columns.
frappe.ui.form.on("Focused Brands", {
	value(frm) {
		if (frm.doctype === "Project") avientek_project_convert_budget(frm);
	},
});

// Re-fetch the exchange rate and recompute both USD columns. Called ONLY from
// the budget/company handlers — that is what makes the rate "frozen" for every
// other kind of edit.
function avientek_project_convert_budget(frm) {
	if (!frm.doc.company) return;

	const amount = flt(frm.doc.custom_budget_amount);
	const value = flt(frm.doc.custom_budget_value);
	const brand_rows = frm.doc.custom_focused_brands || [];
	const has_brand_value = brand_rows.some((row) => flt(row.value));

	if (!amount && !value && !has_brand_value) {
		frm.set_value("custom_exchange_rate", 0);
		frm.set_value("custom_budget_amount_usd", 0);
		frm.set_value("custom_budget_value_usd", 0);
		brand_rows.forEach((row) => frappe.model.set_value(row.doctype, row.name, "value_usd", 0));
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
			brand_rows.forEach((row) => frappe.model.set_value(
				row.doctype, row.name, "value_usd", flt(flt(row.value) / d.exchange_rate, 2)));
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

// Edit lock (point 13). The server decides and enforces; `__onload.edit_lock`
// (avientek.events.project.load_edit_lock) only drives the banner, buttons and
// read-only fields here.
function avientek_project_edit_lock(frm) {
	// set_df_property sticks to this project across reloads, so undo the
	// previous run first (e.g. right after an approval unlocks the form).
	const undo_all = (frm._avientek_lock_undo = frm._avientek_lock_undo || {});
	(undo_all[frm.doc.name] || []).forEach(([fieldname, prop, value]) =>
		frm.set_df_property(fieldname, prop, value));
	const undo = (undo_all[frm.doc.name] = []);

	const lock = (frm.doc.__onload || {}).edit_lock;
	if (!lock || !lock.locked) return;

	const what = __("This project is {0} and closes within {1} months, so it is locked.",
		[frm.doc.custom_project_status, lock.months]);
	const call = (method, args, done) => frappe.call({
		method: `avientek.events.project.${method}`,
		args: Object.assign({ project: frm.doc.name }, args),
		freeze: true,
		callback: (r) => {
			if (r.exc) return;
			done && done(r.message);
			frm.reload_doc();
		},
	});

	if (lock.is_approver) {
		if (lock.requested_by) {
			frm.set_intro(__("{0} {1} asked to edit it: {2}", [what,
				frappe.utils.escape_html(lock.requested_by_name).bold(),
				frappe.utils.escape_html(lock.request_reason || "")]), "yellow");
			frm.add_custom_button(__("Allow Edit"), () => call("allow_project_edit", {},
				() => frappe.show_alert({ message: __("Edit allowed"), indicator: "green" })),
				__("Edit Request"));
			frm.add_custom_button(__("Decline"), () => frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason (optional)") },
				(v) => call("decline_project_edit", { reason: v.reason }),
				__("Decline Edit Request"), __("Decline")), __("Edit Request"));
		} else {
			frm.set_intro(__("{0} You can edit it as a Project L2 Approver.", [what]), "blue");
		}
		return;
	}

	if (lock.unlocked_for_me) {
		frm.set_intro(__("Edit approved. You can save this project once, until {0}.",
			[frappe.datetime.str_to_user(lock.unlocked_until)]), "green");
		return;
	}

	// Locked for this user: every field read-only, except that an Approved
	// project may still be moved to Closed without approval.
	const can_close = frm.doc.custom_project_status === "Approved";
	const lock_prop = (fieldname, prop, value) => {
		const df = frappe.meta.get_docfield(frm.doctype, fieldname, frm.doc.name);
		undo.push([fieldname, prop, df[prop]]);
		frm.set_df_property(fieldname, prop, value);
	};
	frm.fields.forEach((field) => {
		const df = field.df;
		if (!df || !df.fieldname || df.read_only) return;
		if (frappe.model.no_value_type.includes(df.fieldtype)
			&& !frappe.model.table_fields.includes(df.fieldtype)) return;
		if (can_close && df.fieldname === "custom_project_status") return;
		lock_prop(df.fieldname, "read_only", 1);
	});
	if (can_close) {
		lock_prop("custom_project_status", "options", "Approved\nClosed");
	}

	if (lock.requested_by) {
		frm.set_intro(lock.requested_by === frappe.session.user
			? __("{0} Your edit request is waiting for a Project L2 Approver.", [what])
			: __("{0} {1} has an edit request waiting.",
				[what, frappe.utils.escape_html(lock.requested_by_name).bold()]), "orange");
		return;
	}
	frm.set_intro(__("{0} Click Request Edit to ask a Project L2 Approver.", [what]), "orange");
	frm.add_custom_button(__("Request Edit"), () => frappe.prompt(
		{ fieldname: "reason", fieldtype: "Small Text", reqd: 1,
			label: __("What do you need to change, and why?") },
		(v) => call("request_project_edit", { reason: v.reason },
			() => frappe.show_alert({ message: __("Edit request sent"), indicator: "green" })),
		__("Request Edit"), __("Send")));
}
