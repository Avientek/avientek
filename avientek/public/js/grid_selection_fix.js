/**
 * Grid selection handler fix (stopgap).
 *
 * Sridhar/Rahul 2026-07-02, SO-LTD-26-27-00387-1: "Create → Purchase Order"
 * (and any child-table checkbox selection) throws on the server currently
 * deployed to the dedicated Frappe Cloud instance:
 *
 *   Uncaught TypeError: this.update_selection_banner is not a function
 *     at HTMLInputElement.<anonymous> (grid.js:221)
 *     at ...make_purchase_order (sales_order.js)
 *
 * Root cause is in FRAPPE CORE, not Avientek: on the deployed Frappe version,
 * Grid.setup_check() binds its ".grid-row-check" change handler with a plain
 * function(), so inside it `this` is the checkbox <input>, not the Grid — so
 * this.update_selection_banner() / this.refresh_remove_rows_button() don't
 * exist and the action dies. Frappe fixed this in a newer release (our local
 * bench, 15.113.1, already uses an arrow function and works).
 *
 * PROPER FIX: update Frappe/ERPNext on the dedicated server to >= 15.113.1
 * and rebuild assets. This file is a STOPGAP so PO creation works until then —
 * it re-installs setup_check with the corrected arrow-function binding (a copy
 * of the fixed core version) and guards the two method calls. REMOVE this file
 * once the server is upgraded.
 */
frappe.provide("frappe.ui.form");

(function () {
	if (!frappe.ui || !frappe.ui.form || !frappe.ui.form.Grid) return;

	frappe.ui.form.Grid.prototype.setup_check = function () {
		this.wrapper.on("click", ".grid-row-check", (e) => {
			const $check = $(e.currentTarget);
			const checked = $check.prop("checked");
			const is_select_all = $check.parents(".grid-heading-row:first").length !== 0;
			const docname = $check.parents(".grid-row:first")?.attr("data-name");

			if (is_select_all) {
				// (un)check all visible checkboxes
				this.form_grid.find(".grid-row-check").prop("checked", checked);

				// set following rows as checked in model
				let result_length = this.grid_pagination.get_result_length();
				let page_index = this.grid_pagination.page_index;
				let page_length = this.grid_pagination.page_length;
				for (let ri = (page_index - 1) * page_length; ri < result_length; ri++) {
					this.grid_rows[ri]?.select(checked);
				}
			} else if (docname) {
				if (e.shiftKey && this.last_checked_docname) {
					this.check_range(docname, this.last_checked_docname, checked);
				}
				this.grid_rows_by_docname[docname]?.select(checked);
				this.last_checked_docname = docname;
			}

			// Guarded — these exist on current Frappe; no-op on versions that lack them.
			if (typeof this.refresh_remove_rows_button === "function") {
				this.refresh_remove_rows_button();
			}
			if (typeof this.update_selection_banner === "function") {
				this.update_selection_banner();
			}
		});
	};
})();
