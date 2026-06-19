// ── Avientek List View customization for Delivery Note ──
// Jithin 2026-06-19: voided Drafts should appear visually distinct
// in the list view (red "Cancelled (Voided)" indicator) instead of
// the standard orange "Draft" badge. Keeps the row visible (so the
// audit trail is browseable) but flags it clearly so users don't
// confuse it with active Drafts they should still be working on.
frappe.listview_settings['Delivery Note'] = frappe.listview_settings['Delivery Note'] || {};

// Pull the void flag along with the standard row data so we can
// branch on it in get_indicator without an extra fetch.
const _existing_fields = frappe.listview_settings['Delivery Note'].add_fields || [];
frappe.listview_settings['Delivery Note'].add_fields = [
    ..._existing_fields,
    'custom_is_void',
];

// Override the standard indicator. Voided Drafts → red. All other
// rows → fall back to Frappe's built-in status logic.
const _existing_get_indicator = frappe.listview_settings['Delivery Note'].get_indicator;
frappe.listview_settings['Delivery Note'].get_indicator = function (doc) {
    if (doc.docstatus === 0 && cint(doc.custom_is_void)) {
        return [__('Cancelled (Voided)'), 'red', 'custom_is_void,=,1'];
    }
    if (_existing_get_indicator) {
        return _existing_get_indicator(doc);
    }
    // Frappe's default fallback by docstatus
    if (doc.docstatus === 0) return [__('Draft'), 'red', 'docstatus,=,0'];
    if (doc.docstatus === 1) {
        const status_map = {
            'To Bill': 'orange',
            'Completed': 'green',
            'Closed': 'green',
            'Return Issued': 'grey',
        };
        return [__(doc.status), status_map[doc.status] || 'orange', 'status,=,' + doc.status];
    }
    if (doc.docstatus === 2) return [__('Cancelled'), 'red', 'docstatus,=,2'];
};
