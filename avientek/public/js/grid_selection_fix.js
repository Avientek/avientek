/**
 * Grid selection crash stopgap — "Create → Purchase Order" from a Sales Order.
 *
 * Sridhar/Rahul 2026-07-02, SO-LTD-26-27-00387-1 / SO-FZCO-26-01419:
 *
 *   Uncaught TypeError: this.update_selection_banner is not a function
 *     at HTMLInputElement.<anonymous> (grid.js:221)
 *     at SalesOrderController.make_purchase_order (sales_order.js:1363)
 *
 * make_purchase_order opens a "Select Items" dialog and programmatically clicks
 * the grid's select-all checkbox:
 *     dialog.wrapper.find(".grid-heading-row .grid-row-check").click();
 * On the Frappe version deployed to the dedicated server, that grid change
 * handler runs with `this` bound to the checkbox <input> (not the Grid), so
 * this.update_selection_banner() / this.refresh_remove_rows_button() are not
 * functions and it throws — killing PO creation. This is a FRAPPE CORE bug,
 * fixed in newer Frappe. Not an Avientek bug.
 *
 * IMPORTANT: on this deployed version the Grid class is NOT exposed at
 * `frappe.ui.form.Grid` (confirmed live: reading its .prototype throws), so we
 * CANNOT monkey-patch setup_check. The only reliable, version-independent fix
 * is to make those two method names harmless no-ops when they land on an
 * <input>. They are Frappe-Grid-specific names — no real <input> uses them, so
 * this has no side effects. On a fixed Frappe version the methods resolve on
 * the Grid object as normal and these fallbacks are never hit.
 *
 * PROPER FIX: upgrade Frappe/ERPNext on the dedicated server (>= 15.113.1) and
 * rebuild assets, then DELETE this file.
 */
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
		/* never let the shim itself break the desk */
	}
})();
