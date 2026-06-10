"""Sridhar/Rahul 2026-06-10 — Filter typeahead on prod Quotation list
shows "Workflow State" TWICE; local shows only ONE entry. The Custom
Field config is identical between prod and local:

  Quotation-workflow_state   hidden=1  in_standard_filter=0  label="Workflow State"
  Quotation-workflow_status  hidden=0  in_standard_filter=1  label="Workflow State"
                             depends_on="eval:0"   (form-side only)

The Frappe filter typeahead respects `hidden=1` and should hide the
first one. Prod's Redis-cached Quotation meta must be stale (the
2026-06-05 clean_quotation_workflow_state_filter_dropdown patch
cleared cache then, but something between then and now refilled it
with an older snapshot showing hidden=0).

This patch:
  1. Reasserts hidden=1 on the legacy Custom Field (cheap idempotent).
  2. Adds a Property Setter report_hide=1 as belt-and-suspenders so
     the picker definitively skips it even if some Frappe code path
     ignores hidden on Link fields.
  3. Hard-clears Quotation meta cache (in-process + Redis namespace).
  4. Purges per-user __UserSettings Redis shadow for the Quotation
     doctype (Sridhar memory: __UserSettings is Redis-shadowed and
     the picker caches its column/filter state there).

Why `report_hide` is safe here: the hidden legacy CF (workflow_state)
already has hidden=1, so the Pick Columns picker doesn't show it —
no user can have it in a saved Report View layout. Sridhar's general
warning about `report_hide` silently dropping saved columns doesn't
apply when the field was already invisible to begin with.

Idempotent.
"""
import frappe


def _reassert_hidden_on_legacy_cf():
    cf = "Quotation-workflow_state"
    if not frappe.db.exists("Custom Field", cf):
        print(f"[dedupe_quotation_workflow_state_picker] {cf} missing — skip")
        return
    cur = frappe.db.get_value("Custom Field", cf, "hidden")
    if cur == 1:
        print(f"[dedupe_quotation_workflow_state_picker] {cf}.hidden already 1")
        return
    frappe.db.set_value("Custom Field", cf, "hidden", 1, update_modified=False)
    print(f"[dedupe_quotation_workflow_state_picker] {cf}.hidden set 1 (was {cur!r})")


def _set_report_hide_property_setter():
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter
    make_property_setter(
        "Quotation",
        "workflow_state",
        "report_hide",
        "1",
        "Check",
        validate_fields_for_doctype=False,
    )
    print("[dedupe_quotation_workflow_state_picker] Property Setter "
          "Quotation.workflow_state.report_hide=1 set "
          "(belt-and-suspenders against picker showing hidden=1 fields)")


def _hard_clear_quotation_cache():
    """Frappe's clear_cache(doctype=...) clears the meta cache but
    sometimes Redis retains the doctype JSON under multiple keys
    depending on language / hooks. Belt-and-suspenders: also clear
    the wildcard 'doctype' cache namespace.
    """
    try:
        frappe.clear_cache(doctype="Quotation")
        print("[dedupe_quotation_workflow_state_picker] frappe.clear_cache(doctype='Quotation') done")
    except Exception as e:
        print(f"[dedupe_quotation_workflow_state_picker] clear_cache error: {e}")

    try:
        cache = frappe.cache()
        keys_cleared = 0
        for ns in ["doctype_meta", "meta", "form_meta"]:
            try:
                cache.hdel(ns, "Quotation")
                keys_cleared += 1
            except Exception:
                pass
        print(f"[dedupe_quotation_workflow_state_picker] cleared {keys_cleared} "
              f"redis hashtable entries for Quotation")
    except Exception as e:
        print(f"[dedupe_quotation_workflow_state_picker] redis hdel error: {e}")


def _purge_user_settings_for_quotation():
    """The list-view picker caches column/filter state in __UserSettings
    keyed Quotation::<user>. Without purge, users see stale picker
    options until they manually reset filters or log out + back in.
    """
    try:
        users = [r.name for r in frappe.db.sql(
            "SELECT name FROM `tabUser` WHERE enabled=1", as_dict=True
        )]
        cache = frappe.cache()
        for u in users:
            cache.hdel("_user_settings", f"Quotation::{u}")
        print(f"[dedupe_quotation_workflow_state_picker] purged "
              f"__UserSettings for {len(users)} active users")
    except Exception as e:
        print(f"[dedupe_quotation_workflow_state_picker] user-settings "
              f"purge skipped: {e}")


def execute():
    _reassert_hidden_on_legacy_cf()
    _set_report_hide_property_setter()
    frappe.db.commit()
    _hard_clear_quotation_cache()
    _purge_user_settings_for_quotation()
    print("[dedupe_quotation_workflow_state_picker] done")
