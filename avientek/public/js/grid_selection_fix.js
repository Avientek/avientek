/**
 * Grid selection handler fix (stopgap).
 *
 * Sridhar/Rahul 2026-07-02, SO-LTD-26-27-00387-1: "Create → Purchase Order"
 * fails on the server currently deployed to the dedicated Frappe Cloud
 * instance:
 *
 *   Uncaught TypeError: this.update_selection_banner is not a function
 *     at HTMLInputElement.<anonymous> (grid.js:221)
 *     at SalesOrderController.make_purchase_order (sales_order.js:1363)
 *
 * make_purchase_order builds a "Select Items" dialog and programmatically
 * clicks the grid's select-all checkbox:
 *     dialog.wrapper.find(".grid-heading-row .grid-row-check").click();
 * That fires Grid.setup_check()'s ".grid-row-check" handler. On the deployed
 * Frappe version that handler is a plain function(), so inside it `this` is the
 * checkbox <input> (not the Grid) and this.update_selection_banner() /
 * this.refresh_remove_rows_button() don't exist → it throws and PO creation
 * dies. This is a FRAPPE CORE bug, fixed upstream (our local bench 15.113.1
 * uses an arrow function and works). Not an Avientek bug.
 *
 * PROPER FIX: upgrade Frappe/ERPNext on the dedicated server to >= 15.113.1
 * and rebuild assets, then DELETE this file. Until then this stopgap applies
 * TWO independent safety nets:
 *
 *   1. Re-install Grid.prototype.setup_check with the corrected arrow-function
 *      binding (retried until the Grid class is defined, so it can't lose the
 *      race with app_include_js load order).
 *   2. Add harmless no-op fallbacks for the two grid methods on
 *      HTMLInputElement.prototype, so even if (1) doesn't match the deployed
 *      version's internals, a mis-bound `this.update_selection_banner()` /
 *      `this.refresh_remove_rows_button()` on an <input> can never throw.
 *      These names are Frappe-Grid-specific; no real <input> uses them.
 */

// ── Safety net 2: no-op fallbacks on HTMLInputElement (belt-and-suspenders) ──
(function () {
	try {
		["update_selection_banner", "refresh_remove_rows_button"].forEach(function (m) {
			if (!(m in HTMLInputElement.prototype)) {
				Object.defineProperty(HTMLInputElement.prototype, m, {
					value: function () {},
					writable: true,
					configurable: true,
					enumerable: false,
				});
			}
		});
	} catch (e) {
		/* ignore */
	}
})();

// ── Safety net 1: reinstall the corrected setup_check (retry for load order) ──
(function applySetupCheckFix(attempt) {
	attempt = attempt || 0;
	if (!(window.frappe && frappe.ui && frappe.ui.form && frappe.ui.form.Grid)) {
		if (attempt < 100) {
			setTimeout(function () {
				applySetupCheckFix(attempt + 1);
			}, 50);
		}
		return;
	}

	frappe.ui.form.Grid.prototype.setup_check = function () {
		this.wrapper.on("click", ".grid-row-check", (e) => {
			const $check = $(e.currentTarget);
			const checked = $check.prop("checked");
			const is_select_all = $check.parents(".grid-heading-row:first").length !== 0;
			const docname = $check.parents(".grid-row:first")?.attr("data-name");

			if (is_select_all) {
				this.form_grid.find(".grid-row-check").prop("checked", checked);

				let result_length =
					this.grid_pagination && this.grid_pagination.get_result_length
						? this.grid_pagination.get_result_length()
						: (this.grid_rows || []).length;
				let page_index = this.grid_pagination ? this.grid_pagination.page_index : 1;
				let page_length = this.grid_pagination
					? this.grid_pagination.page_length
					: result_length;
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

			if (typeof this.refresh_remove_rows_button === "function") {
				this.refresh_remove_rows_button();
			}
			if (typeof this.update_selection_banner === "function") {
				this.update_selection_banner();
			}
		});
	};
})();
