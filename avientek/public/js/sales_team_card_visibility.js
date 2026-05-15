// Sammish 2026-05-15 — Hide management-only Number Cards on Sales Team
// workspace from users who don't have one of the permitted roles.
//
// Frappe v15 Number Card has no native role-restriction field, so
// the cards are public on the workspace JSON. This script hides
// them client-side when the user lacks any of the management roles.
// Public is_company_account / Quotation perm_query still controls
// what data the card COUNT shows — this is purely about chrome.

(function () {
    const ALLOWED_ROLES = [
        "Sales Manager",
        "Sales Director",
        "GM",
        "Finance Manager",
        "System Manager",  // sysadmin sees everything
        "Administrator",
    ];

    const RESTRICTED_CARDS = new Set([
        "Cancelled Quotations",
        "Quotes Requested for Update",
    ]);

    function user_has_allowed_role() {
        const my_roles = (frappe.user_roles || frappe.boot.user.roles || []);
        return ALLOWED_ROLES.some((r) => my_roles.indexOf(r) >= 0);
    }

    function hide_restricted_cards() {
        if (user_has_allowed_role()) return;
        // Frappe renders each Number Card inside a `.widget` div with a
        // `.widget-title` containing the card label. Iterate and hide.
        document.querySelectorAll(".widget").forEach((w) => {
            const title_el = w.querySelector(".widget-title, .widget-head .widget-title");
            const title = title_el ? (title_el.textContent || "").trim() : "";
            if (RESTRICTED_CARDS.has(title)) {
                w.style.display = "none";
            }
        });
    }

    function on_sales_team_workspace() {
        // route can be "sales-team" or wrapped in workspace shell
        const route = (frappe.get_route() || []).join("/").toLowerCase();
        return route === "workspace/sales-team" || route === "sales-team";
    }

    function tick() {
        if (!on_sales_team_workspace()) return;
        hide_restricted_cards();
    }

    // Run on initial load + on route changes. Number Cards render async
    // so re-check a few times after a route change.
    $(document).on("startup", tick);
    $(document).on("page-change", function () {
        if (!on_sales_team_workspace()) return;
        setTimeout(hide_restricted_cards, 400);
        setTimeout(hide_restricted_cards, 1200);
        setTimeout(hide_restricted_cards, 2500);
    });

    // Also run once after current page settles (in case we boot
    // directly into Sales Team).
    $(function () {
        setTimeout(tick, 800);
        setTimeout(tick, 2000);
    });
})();
