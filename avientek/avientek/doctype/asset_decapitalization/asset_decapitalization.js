// Copyright (c) 2026, Avientek and contributors
// For license information, please see license.txt

frappe.ui.form.on("Asset Decapitalization", {

	refresh(frm) {
		// View Asset button after submit
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Asset"), () => {
				frappe.set_route("Form", "Asset", frm.doc.asset);
			}, __("View"));

			frm.add_custom_button(__("Accounting Ledger"), () => {
				frappe.set_route("query-report", "General Ledger", {
					voucher_no: frm.doc.name,
					company: frm.doc.company,
				});
			}, __("View"));

			frm.add_custom_button(__("Stock Ledger"), () => {
				frappe.set_route("query-report", "Stock Ledger", {
					voucher_no: frm.doc.name,
					company: frm.doc.company,
				});
			}, __("View"));
		}

		// Query: only submitted assets that aren't disposed
		frm.set_query("asset", () => ({
			filters: {
				docstatus: 1,
				status: ["not in", ["Draft", "Scrapped", "Sold", "Capitalized", "Cancelled"]],
			},
		}));

		// Query: only stock items
		frm.set_query("target_item_code", () => ({
			filters: { is_stock_item: 1 },
		}));

		// Query: leaf warehouses in same company
		frm.set_query("target_warehouse", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));

		// Query: cost centers in same company
		frm.set_query("cost_center", () => ({
			filters: { company: frm.doc.company },
		}));

		// Query: batch for target item
		frm.set_query("batch_no", () => ({
			filters: { item: frm.doc.target_item_code },
		}));

		// Query: gain/loss account — income or expense accounts in same company
		frm.set_query("gain_loss_account", () => ({
			filters: {
				company: frm.doc.company,
				root_type: ["in", ["Income", "Expense"]],
				is_group: 0,
			},
		}));
	},

	asset(frm) {
		if (!frm.doc.asset) {
			frm.set_value("asset_name", "");
			frm.set_value("item_code", "");
			frm.set_value("gross_purchase_amount", 0);
			frm.set_value("value_after_depreciation", 0);
			frm.set_value("accumulated_depreciation", 0);
			frm.set_value("entry_value", 0);
			frm.set_value("gain_loss_amount", 0);
			return;
		}

		frappe.db.get_value("Asset", frm.doc.asset, [
			"asset_name", "item_code", "company", "asset_category",
			"gross_purchase_amount", "value_after_depreciation",
		], (r) => {
			if (!r) return;
			frm.set_value("asset_name", r.asset_name);
			frm.set_value("item_code", r.item_code);
			frm.set_value("company", r.company);
			frm.set_value("asset_category", r.asset_category);
			frm.set_value("gross_purchase_amount", r.gross_purchase_amount || 0);
			frm.set_value("value_after_depreciation", r.value_after_depreciation || 0);
			frm.set_value("accumulated_depreciation",
				flt(r.gross_purchase_amount) - flt(r.value_after_depreciation));
			frm.set_value("entry_value", r.value_after_depreciation || 0);
			frm.set_value("gain_loss_amount", 0);

			// Auto-set gain/loss account from Asset Category's depreciation expense account
			if (r.asset_category && r.company) {
				frappe.call({
					method: "avientek.events.asset_capitalization.get_depreciation_expense_account",
					args: { asset_category: r.asset_category, company: r.company },
					callback(cat_r) {
						if (cat_r.message) {
							frm.set_value("gain_loss_account", cat_r.message);
						}
					},
				});
			}

			// Auto-set target_item_code if the asset's item is a stock item
			if (r.item_code) {
				frappe.db.get_value("Item", r.item_code, "is_stock_item", (item_r) => {
					if (item_r && item_r.is_stock_item) {
						frm.set_value("target_item_code", r.item_code);
					}
				});
			}
		});
	},

	entry_value(frm) {
		if (flt(frm.doc.entry_value) < 0) {
			frappe.msgprint(__("Stock Entry Value cannot be negative"));
			frm.set_value("entry_value", frm.doc.value_after_depreciation || 0);
			return;
		}
		frm.set_value("gain_loss_amount",
			flt(frm.doc.value_after_depreciation) - flt(frm.doc.entry_value));
	},
});
