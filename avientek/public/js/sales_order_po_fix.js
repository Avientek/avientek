/**
 * "Purchase Order (Direct)" — reliable Create-PO from a Sales Order.
 *
 * Sridhar/Rahul 2026-07-02, SO-FZCO-26-01419 / SO-LTD-26-27-00387-1:
 * the standard Create → Purchase Order crashes on the Frappe version deployed
 * to the dedicated server:
 *   Uncaught TypeError: this.update_selection_banner is not a function
 *     at HTMLInputElement.<anonymous> (grid.js:221)
 *     at SalesOrderController.make_purchase_order (sales_order.js:1363)
 * ERPNext's make_purchase_order opens a "Select Items" dialog and clicks the
 * grid's select-all checkbox; the deployed grid's change handler is mis-bound
 * (`this` is the <input>, not the Grid), so it throws and no PO is made. It is
 * a Frappe core bug (fixed in >= 15.113.1); the Grid class isn't even exposed
 * as frappe.ui.form.Grid on that version, so it can't be monkey-patched.
 *
 * This button SKIPS the broken dialog entirely: it collects the pending
 * (not-yet-ordered) Sales Order items and calls the same whitelisted server
 * maker directly, then opens the resulting Purchase Order — no grid, no crash.
 * Verified on avintek.local (SO-LTD-26-27-00231 → PO with 12 items).
 *
 * PROPER FIX: upgrade Frappe/ERPNext on the dedicated server (>= 15.113.1),
 * after which the standard Create → Purchase Order works and this file + the
 * grid_selection_fix.js stopgap can be removed.
 */
frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;

		frm.add_custom_button(
			__("Purchase Order (Direct)"),
			() => avientek_make_po_direct(frm),
			__("Create")
		);
	},
});

function avientek_make_po_direct(frm) {
	const selected_items = [];
	(frm.doc.items || []).forEach((d) => {
		// Pending = ordered short of stock qty (mirrors ERPNext's own check).
		const pending_qty = flt(d.stock_qty) - flt(d.ordered_qty);
		if (pending_qty > 0) {
			selected_items.push({ item_code: d.item_code, sales_order_item: d.name });
		}
	});

	if (!selected_items.length) {
		frappe.msgprint({
			message: __("Purchase Order already created for all Sales Order items"),
			title: __("Note"),
			indicator: "blue",
		});
		return;
	}

	frappe.call({
		method: "erpnext.selling.doctype.sales_order.sales_order.make_purchase_order",
		args: {
			source_name: frm.doc.name,
			selected_items: selected_items,
		},
		freeze: true,
		freeze_message: __("Creating Purchase Order ..."),
		callback(r) {
			if (!r.exc && r.message) {
				frappe.model.sync(r.message);
				frappe.set_route("Form", r.message.doctype, r.message.name);
			}
		},
	});
}
