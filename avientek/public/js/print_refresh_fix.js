/**
 * Print preview stale-document stopgap (ERP-TKT-15).
 *
 * On the Frappe version deployed to the dedicated server, opening one document's
 * print view (e.g. PRF AVLLC-01005) then navigating to another (AVLTD-01673)
 * sometimes leaves the PREVIOUS document rendered in the preview ("old buffer") —
 * a client-side print-view refresh quirk (fixed in newer Frappe). The print
 * format itself is correct (it renders doc.name server-side), so this is purely
 * a stale-render issue, not wrong data.
 *
 * This forces a fresh full render only when the user SWITCHES between two
 * different print documents. Opening the first print view (from a form/list)
 * does NOT reload, so there's no flash on normal use. It touches no print
 * internals — only routing + a full reload — so it's low-risk.
 *
 * Remove after Frappe/ERPNext is upgraded on the dedicated server (>=15.113.1).
 */
(function () {
	if (!window.frappe || !frappe.router || !frappe.router.on) return;

	function printKey() {
		try {
			var r = frappe.get_route ? frappe.get_route() : null;
			if (r && String(r[0]).toLowerCase() === "print" && r[1] && r[2]) {
				return r[1] + "/" + r[2];
			}
		} catch (e) {}
		return null;
	}

	// Seed from the current route so a direct load on a print URL is tracked.
	var last = printKey();

	frappe.router.on("change", function () {
		var key = printKey();
		if (!key) {
			last = null; // left the print view
			return;
		}
		if (last && last !== key) {
			// Switched to a DIFFERENT print document — the preview may be stale
			// on this Frappe version. Reload the current (new) print URL so the
			// server re-renders it fresh.
			last = key;
			window.location.reload();
			return;
		}
		last = key; // first print view opened — no reload, no flash
	});
})();
