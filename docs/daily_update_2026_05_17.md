# PRF rollout — 2026-05-17

## Headline

**PRF Released → Processed tracking + Internal-party bank account support + half-dozen polish fixes.**

Seven workstreams shipped across the PRF, Payment Entry, Bank Account, and Sales Team workspace surfaces. One new Script Report. One Custom Field. Two new workflow states. One back-fill patch. All smoke-tested on `avientekv21.local`.

---

## What shipped today

### 1. "Not Saved" pill flashing on saved-doc load — fixed

Replaced the racing 500 ms `__unsaved` poller with a `frm.dirty` + `frm.toolbar.set_indicator_for_dirty` stub for the first 5 seconds (or until the user touches an input). Both chokepoints are neutralised, so no path that flips the pill can fire during the initial-load window. Real edits still dirty the form normally once the window closes.

**Files:** `payment_request_form.js`

### 2. Payment Request Form Summary — new Script Report

Consolidated Net Amount + Currency pair via `CASE` on `payment_type` (Internal Transfer → `issued_amount` / `issued_currency`; Pay / Advance Pay → `total_outstanding_amount` / `currency`). Eight filters, last-90-days default, three access entry points: PRF list `Menu → Summary Report`, Sales Team workspace shortcut card, direct URL `/app/query-report/Payment Request Form Summary`. Smoke run returned 27 rows correctly.

**Files:** `report/payment_request_form_summary/__init__.py`, `*.json`, `*.py`, `*.js`; `payment_request_form_list.js`; `workspace/sales_team/sales_team.json`

### 3. "Combined PDF building" banner — removed

Deleted the entire 251-line persistent banner block (`PRF_JOB_LS_KEY`, `prf_save_job`, `prf_load_job`, `prf_clear_job`, `prf_format_elapsed`, `prf_get_or_create_banner_el`, `prf_render_banner`, `prf_stop_banner`, `prf_start_banner`, `prf_cancel_job`). The Download Combined PDF button now silently queues the job; the generated PDF auto-appears in Attachments via the `prf_combined_pdf_ready` realtime listener (kept and simplified to `frm.reload_doc()`).

**Files:** `payment_request_form.js`

### 4. After Released — every field locks

New `apply_released_lock` JS handler. When `workflow_state` is in {Released, Partially Processed, Processed, Cancelled, Rejected}, the three `allow_on_submit=1` fields (`supplier_bank_account`, `additional_documents`, `supplier_balance`) get clamped to read-only, plus the `payment_references` grid loses add/delete-row permission. Wired in `refresh` AFTER `apply_fc_field_unlock` so Finance Controller's edit window in Approved L1/L2 stays intact.

**Files:** `payment_request_form.js`

### 5. Internal-party bank account support

Two-part change:

- **Smart picker query** — `bank_account_query_with_internal` server-side function. PRF `issued_bank` and `receiving_bank` pickers now return Bank Accounts matching `is_company_account=1 AND company=PRF.company` **OR** linked to a Customer with `is_internal_customer=1` **OR** linked to a Supplier with `is_internal_supplier=1`. Mirrors the existing `party_query_with_internal` pattern.
- **Auto-tick `is_company_account`** — `auto_link_internal_company_account` validate hook on Bank Account. Saving any Bank Account linked to an Internal Customer / Supplier auto-ticks the flag so all standard ERPNext `is_company_account` filters (bank reconciliation, payment entry pickers, etc.) recognise it as a company-type account.
- **Back-fill patch** — `backfill_is_company_account_internal_party.py` flips `is_company_account` from 0 → 1 on all existing Bank Accounts linked to internal parties. Idempotent.

**Files:** `payment_request_form.py`, `payment_request_form.js`, `events/bank_account.py`, `hooks.py`, `patches/backfill_is_company_account_internal_party.py`, `patches.txt`

### 6. Party Bank Account auto-fetch + lock

New `supplier_bank_account` change handler. When the user picks a Bank Account on the Party Bank Details tab, Account No / IBAN / Bank / SWIFT auto-fetch from the Bank Account record (SWIFT falls back from `Bank.swift_number` → `Bank Account.branch_code`). Clearing the picker wipes the four dependent fields. All four are clamped read-only in `refresh` — values flow from the master record, not direct edits.

**Files:** `payment_request_form.js`

### 7. PRF Released → Processed payment tracking

End-to-end status flow for PRFs after Release:

- Two new workflow states on the PRF workflow: **Partially Processed** (Warning) and **Processed** (Success). Both `doc_status=1`, `allow_edit=System Manager`.
- New Custom Field on Payment Entry: `payment_request_form` (Link → Payment Request Form). Read-only, set by the picker or by the existing `create_payment_entry` mapper.
- `update_prf_status_on_pe_submit` hook (on_submit + on_cancel). Recomputes the cumulative sum of `base_paid_amount` across every submitted PE keyed to a PRF:
  - sum ≥ `total_outstanding_amount` → **Processed**
  - sum > 0 → **Partially Processed**
  - sum = 0 → **Released** (covers PE cancellation rolling back)
- Reverse-direction picker on Payment Entry: `Get From → Get Payment Request Form` opens a dialog of Released / Partially Processed PRFs filtered by party. Picking one populates `party_type`, `party`, `paid_amount` (suggested = outstanding balance), `mode_of_payment`, `bank_account`, `party_bank_account`, `paid_from`, `paid_to` and links the PE to the PRF via the new Custom Field.
- View linked PRF: on a PE that has `payment_request_form` set, a `View → Open Linked PRF` button takes the user to the source PRF.

**Files:** `patches/add_pe_prf_link_and_processed_states.py`, `events/payment_entry.py`, `hooks.py`, `payment_request_form.py` (whitelisted `get_outstanding_payment_request_forms`), `public/js/payment_entry.js`, `payment_request_form.js` (terminal-state list extended), `patches.txt`

---

## Open items

### Caveat — Internal Transfer status flow uses wrong amount field

The picker SQL and `_recompute_prf_status` compare `base_paid_amount` against `total_outstanding_amount`. For Internal Transfer PRFs `total_outstanding_amount = 0` because that field tracks payment-references outstanding (which IT doesn't populate — IT carries the transfer amount in `issued_amount`). Net effect: any PE booked against an IT PRF lands it in **Partially Processed** forever.

**Fix:** change the comparison field to `CASE WHEN payment_type='Internal Transfer' THEN issued_amount ELSE total_outstanding_amount END` in both the picker SQL and the recompute function.

**Decision needed:** Apply the CASE fix, or exclude Internal Transfer from this status flow entirely (since IT typically settles via Journal Entry rather than Payment Entry)?

### Pending administrative steps

- Frappe Cloud `bench migrate` still needs to be run for production rollout (the local `avientekv21.local` smoke ran clean).
- Browser hard-reload on every user's machine after rollout to pick up the new JS.

---

## Smoke test verification (avientekv21.local)

| Check | Result |
|---|---|
| Migrate applied `add_pe_prf_link_and_processed_states` patch | ✓ |
| Custom Field `Payment Entry-payment_request_form` exists (Link → PRF) | ✓ |
| Workflow State masters `Processed` + `Partially Processed` created | ✓ |
| `get_outstanding_payment_request_forms()` returns 4 Released PRFs | ✓ |
| `_recompute_prf_status("AVWLL-00345")` runs clean | ✓ |
| Payment Request Form Summary report returns 27 rows | ✓ |
| Python + JS syntax all clean | ✓ |
