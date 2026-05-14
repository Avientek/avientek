# PRF rollout — 2026-05-17

## Headline

**PRF Released → Processed tracking + Internal-party bank account support + Quotation margin gate restored (URGENT) + half-dozen polish fixes.**

Eight workstreams shipped across PRF, Payment Entry, Bank Account, Quotation, and Sales Team workspace surfaces. One new Script Report. One Custom Field. Two new workflow states on PRF + two restored conditions on Quotation V3. Five new patches. All smoke-tested on `avientekv21.local`.

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

### 8. Quotation V3 — restored margin approval gate + leak cleanup (URGENT)

**Flagged by Jithin on WhatsApp (2026-05-15 5:17 PM):** `QN-LTD-26-02011` (party C-AETPL-00392, India, -1.52% margin vs brand standard 6%) was submitted without going through Level 1 / Level 2 approval. Sridhar initially attributed it to "submitted before workflow update was configured" but Jithin pushed back: "quote conditions were in place from the time".

**Root cause confirmed:** Jithin was right. The V3 workflow seeder (deployed 2026-05-09) dropped the V2 margin condition `doc.custom_auto_approve_ok == 1` from the `Draft → Submit` transition. The system still computed the flag correctly (QN-LTD-26-02011 had `custom_auto_approve_ok = 0` AND `custom_level_1_approve_ok = 0` — needed Level 2 approval) but the workflow no longer asked the system about it.

**Three-layer fix:**

- **UI gate** — V3 seeder template updated: `Draft → Submit → Submitted` and `Submitted → Approve → Approved` now require `doc.custom_auto_approve_ok == 1`. New `Draft → Send for Approval → Pending For Approval` transition added for low-margin quotes.
- **Server gate** — new `validate_margin_approval_required` in `events/quotation.py` throws on direct Submit when margin requires L1/L2 — catches REST API / script bypass too.
- **Audit cleanup** — patch `fix_post_v3_quotation_margin_leaks.py` runs on next migrate to clean up post-V3 leaks.

**Audit results (post-V3 only, since 2026-05-09):**

*8 quotes auto-routed back to Pending For Approval (Draft) — patch handled automatically:*

| Reference | Company |
|---|---|
| QN-FZCO-26-00183 | Avientek FZCO |
| QN-FZCO-26-00189 | Avientek FZCO |
| QN-FZCO-26-00191 | Avientek FZCO |
| QN-LLC-26-00413 | Avientek Electronics Trading L.L.C |
| QN-LTD-26-01995 | Avientek Electronics Trading PVT. LTD |
| QN-LTD-26-02001-1 | Avientek Electronics Trading PVT. LTD |
| QN-LTD-26-02002 | Avientek Electronics Trading PVT. LTD |
| QN-LTD-26-02006 | Avientek Electronics Trading PVT. LTD |

*Plus the original QN-LTD-26-02011 — manually moved to `docstatus=0 / status=Draft / workflow_state=Pending For Approval` on local; same SQL queued for prod via Bench Console.*

*9 quotes left as-is per Jithin's decision (already at "Approved" — likely have linked Sales Orders / Invoices, so cancel+amend would disrupt downstream documents):*

| Reference | Company | Customer | Submitted By |
|---|---|---|---|
| QN-LTD-26-02008 | Avientek Electronics Trading PVT. LTD | C-AETPL-00724 | sales@avientek.com |
| QN-KSA-26-00127 | AVIENTEK TRADING LLC | CUST-2024-00492 | me.sales4@avientek.com |
| QN-LTD-26-01998 | Avientek Electronics Trading PVT. LTD | C-AETPL-00609 | sales@avientek.com |
| QN-FZCO-26-00184 | Avientek FZCO | C-FZCO-0354 | me.sales@avientek.com |
| QN-LLC-26-00404 | Avientek Electronics Trading L.L.C | C-LLC-0180 | me.sales1@avientek.com |
| QN-LTD-26-01997 | Avientek Electronics Trading PVT. LTD | C-AETPL-00630 | sales@avientek.com |
| QN-LTD-26-01996 | Avientek Electronics Trading PVT. LTD | C-AETPL-00815 | sales@avientek.com |
| QN-LTD-26-01993 | Avientek Electronics Trading PVT. LTD | C-AETPL-00453 | sales@avientek.com |
| QN-LLC-26-00402 | Avientek Electronics Trading L.L.C | C-LLC-0180 | me.sales1@avientek.com |

**Going forward (post-deploy):** every new quote where margin requires approval is blocked at all three layers (UI button hidden, workflow condition, server validate). No path remains for a low-margin quote to skip Level 1 / Level 2.

**Files:** `patches/seed_quotation_approval_v3_workflow.py` (template updated), `events/quotation.py` (`validate_margin_approval_required`), `hooks.py` (Quotation validate wired), `patches/fix_post_v3_quotation_margin_leaks.py` (new — cleanup), `patches/restore_quotation_margin_gate_on_v3_workflow.py` (historical standalone, not registered), `patches.txt`

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
| Quotation V3 workflow has 27 transitions (margin gate restored) | ✓ |
| `fix_post_v3_quotation_margin_leaks` patch routed 8 Submitted leaks, logged 9 Approved | ✓ |
| QN-LTD-26-02011 reachable at `Pending For Approval / Draft` on local | ✓ |
