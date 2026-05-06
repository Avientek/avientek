# Payment Request Form — Manual Test Cases

Distribute to QA / Sridhar / Jithin for manual verification on
**`avientekv21.frappe.cloud`** (or test site) after every Update +
Migrate. Each test case lists the exact precondition, steps, and
expected outcome. Mark Pass/Fail in the right column.

**Latest commit covered:** `be7b3e2` (master, 2026-05-06).
**Re-run cadence:** after every deploy + after any PRF-related code change.

---

## Setup — one-time per tester

| Step | Detail |
|---|---|
| Login | Use a **non-Administrator** account (e.g. `testqcs@gmail.com`) so role-based behaviours surface. Run a few tests as `Administrator` too to confirm bypass. |
| Browser | Chrome/Edge in **Incognito** to avoid cached old form definitions. Hard-refresh (`Cmd+Shift+R`) at the start of each session. |
| Permissions | Confirm the test user has at least: `Sales User`, `Accounts User`, and is in the Sales Team of one Supplier so balance fetch works. |

---

## Section 1 — Naming Series per Company (commit `365303a`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 1.1 | Auto-pick on Company change | New PRF → choose Company = **Avientek FZCO** | naming_series field auto-fills to `AVFZC-.###` | |
| 1.2 | KSA prefix | New PRF → Company = **Avientek Trading LLC** (KSA) | naming_series = `AVKSA-.###` | |
| 1.3 | India prefix | New PRF → Company = **Avientek Electronics Trading Pvt Ltd** | naming_series = `AVLTD-.###` | |
| 1.4 | LLC prefix | New PRF → Company = **Avientek Electronics Trading LLC** | naming_series = `AVLLC-.###` | |
| 1.5 | WLL prefix | New PRF → Company = **Avientek Trading WLL** | naming_series = `AVWLL-.###` | |
| 1.6 | Existing draft untouched | Open an existing **draft** PRF whose naming_series is already set; change Company | naming_series **does not** auto-overwrite an existing value | |
| 1.7 | Submitted doc untouched | Open a submitted PRF; verify Company change is blocked anyway (Frappe rule) | No naming_series side-effect | |

---

## Section 2 — TR Print Format Dynamic Branches (commit `5a066e7`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 2.1 | TR type = Direct | Submit PRF with `payment_type=Pay`, `tr_type=Direct` → Print → Payment Voucher Professional | Header reads **"DOCUMENTS AVAILABLE (Direct)"** with `Proforma Invoice` and `Purchase Order` Yes/No rows. **No "Advance TR" section.** | |
| 2.2 | TR type = ADV (Advance) | Submit PRF with `tr_type=ADV` → Print | Header reads **"DOCUMENTS REQUIRED (Advance TR)"** with the standard Advance doc list | |
| 2.3 | TR type = Sight | Submit PRF with `tr_type=Sight` → Print | Header reads **"DOCUMENTS REQUIRED (Sight TR)"** | |
| 2.4 | TR type = empty / other | PRF with `tr_type` blank | Falls through to **"DOCUMENTS REQUIRED (Open TR)"** branch | |
| 2.5 | Both PV formats | Repeat 2.1 → 2.4 in **Payment Voucher Fast** | Same dynamic branches in landscape format | |

---

## Section 3 — Combined PDF Includes All Payment Types (commit `be7b3e2`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 3.1 | Pay type | Open submitted PRF where `payment_type=Pay` | "Download Combined PDF" button present in the form's button group | |
| 3.2 | **Advance Pay type** | Open submitted PRF where `payment_type=Advance Pay` | "Download Combined PDF" button present (was missing before `be7b3e2`) | |
| 3.3 | **Internal Transfer type** | Open submitted PRF where `payment_type=Internal Transfer` (e.g. `AVFZC-012`) | "Download Combined PDF" button present (was missing before `be7b3e2`) | |
| 3.4 | Combined PDF for Internal Transfer | Click button on an IT PRF | Download starts. The PDF opens to a single page with "INTERNAL TRANSFER VOUCHER" title, sender + receiver bank blocks, exchange rate row, and signatures. | |
| 3.5 | Background queue alive | Click Combined PDF on a Pay PRF with 5+ references | Persistent banner shows "Combined PDF building — elapsed Xs". Banner survives page refresh / tab switch. When done, "Download Now" appears. | |

---

## Section 4 — Supplier Invoice No on Combined PDF (commit `55ba3da`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 4.1 | Header label | On a Pay PRF with at least one Purchase Invoice reference, generate Combined PDF | The invoice table column header is **"Supplier Invoice No"**, not "Invoice No." | |
| 4.2 | Body value | Same PDF | The cell shows the supplier's `bill_no` (e.g. `INV-2024-12345`), not the system reference like `PINV-AT-25-00001` | |
| 4.3 | Reference + Remarks split | Same PDF | The right side has **two separate columns**: Reference and Remarks. Both populated where data exists. | |
| 4.4 | Both PV formats | Repeat 4.1 → 4.3 on Payment Voucher Fast | Same behaviour | |

---

## Section 5 — PV Signature Block (commits `55ba3da`, `23fc040`, `676e798`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 5.1 | Cleaner labels — PV Pro | Print any PRF with PV Professional | Signature row reads `Prepared` / `Authorised` / `Approved` / `Approved` (Siby Joy) / `Approved` (Siby Thomas John). **No** "By", "-By", "Approve Level 1/2", or "Acknowledged-By" labels. | |
| 5.2 | Cleaner labels — PV Fast | Print same PRF with PV Fast | 7 cells: Prepared / Authorised / Approved / Approved / Released / Approved (Siby Joy / Corp. Fin Manager) / Approved (Siby Thomas John / Managing Director) | |
| 5.3 | Dynamic Prepared name | Submit a PRF as User A; print | Prepared cell shows User A's `full_name` (not literal "(User Name)") | |
| 5.4 | Dynamic Authorised name | After workflow advances to Authorised by User B; print | Authorised cell shows User B's name | |
| 5.5 | Dynamic Approve L1 name | After workflow reaches Approved Level 1 by User C; print | First Approved cell shows User C | |
| 5.6 | Approved L2 name | After Approved Level 2; print | Second Approved cell shows L2 approver name | |
| 5.7 | Released | After Released state; print | Released cell shows Released-by user | |
| 5.8 | Siby spaces always present | Print any PRF | Last 2 cells always show "Siby Joy / Corp. Fin Manager" and "Siby Thomas John / Managing Director" — even if no user has signed yet | |

---

## Section 6 — Workflow Self-Approval Block (commit `c38aa36`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 6.1 | Creator cannot Authorise own | User A creates draft PRF, fills all required fields, saves. User A then attempts the **Authorise** workflow action | Frappe blocks with "Self-approval is not allowed" error. State stays Draft. | |
| 6.2 | Different user can Authorise | User B (with `Accounts Manager` role) opens the same PRF and clicks Authorise | Transition succeeds; state → Authorised | |
| 6.3 | L1 cannot self-approve L2 | User C does Approve L1; same User C tries Approve L2 | Blocked. Different user must do L2. | |
| 6.4 | Released cannot self-release | User D approves L2; same User D tries Release Payment | Blocked. Different Finance Controller must release. | |
| 6.5 | Persists across migrate | After next bench migrate, repeat 6.1 | Still blocked (after_migrate guard re-asserts) | |

---

## Section 7 — Cross-Company Outstanding Balance (commit `365303a`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 7.1 | Single-company supplier | New PRF, party = a Supplier with GL postings only in one Company | `supplier_balance` matches the standard ERPNext Aging report for that company | |
| 7.2 | Cross-company supplier | New PRF, party = `INT-S004` (intercompany supplier with rows in 5 companies); Company = `AVIENTEK TRADING LLC` | `supplier_balance` is the SUM across all 5 companies, converted to PRF currency. Should show much larger absolute number than ERPNext's per-company aging | |
| 7.3 | Loose-JV addition | Verify a JV with party_type/party blank but on the supplier's payable GL is reflected in the balance | Helper picks it up via `_with_jv_inclusion` layer | |
| 7.4 | Currency conversion | PRF currency = USD, supplier balance is in AED | Balance shown in USD at posting_date FX rate | |

---

## Section 8 — Outstanding Balance in Document Currency (commit `594f677`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 8.1 | Doc currency display | New PRF, set Currency = USD | `supplier_balance` field's number formatting follows USD (not company AED) | |
| 8.2 | Currency change refresh | Change PRF currency from USD → EUR | `supplier_balance` re-computes at EUR rate | |

---

## Section 9 — Previous Payment History Code Dynamic (commit `365303a`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 9.1 | TT mode | Open PRF for a supplier with prior Payment Entry mode_of_payment="TT-AED"; expand the Previous Payment History panel | Type column shows **TT** | |
| 9.2 | TR mode | Same supplier with mode "Trust Receipt" | Type column shows **TR** | |
| 9.3 | LC mode | mode "Letter of Credit" | Type column shows **LC** (not TT — that was the bug) | |
| 9.4 | Cheque | mode "Cheque" | Type column shows **CHQ** | |
| 9.5 | Cash | mode "Cash" | Type column shows **CASH** | |
| 9.6 | NEFT / RTGS | mode "NEFT" or "RTGS" | Type column shows **BT** | |
| 9.7 | Visa Card | mode "Visa Card" | Type column shows **CARD** | |
| 9.8 | Empty mode | mode blank | Type column shows **PAY** | |

---

## Section 10 — Advance Pay Reference Table (commits `5a066e7`, `23fc040`, `676e798`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 10.1 | Reference table now visible | New PRF, payment_type = **Advance Pay** | Payment References section + table visible (was hidden before `23fc040`) | |
| 10.2 | Table columns | Inspect the row entry form | Columns: Type, Invoice, Invoice Date, Due Date, Currency, Billing Amount, Outstanding, Document Reference, View | |
| 10.3 | Manual row | Add Row → Type=Manual → enter free-text in Document Reference | Saves without error | |
| 10.4 | Hide redundant scalar fields | Same Advance Pay PRF | The legacy `Advance Amount` and `Advance Reference` single-line fields are **hidden** | |
| 10.5 | Currency from party | Add a row with Type=Manual; check Currency cell | Defaults to **party master currency** (e.g. USD if Supplier's `default_currency=USD`), not company AED | |
| 10.6 | Currency fallback | Party with no `default_currency` set | Falls back to company default | |
| 10.7 | Get Open Purchase Orders button | New PRF, payment_type=Advance Pay, Supplier party | Button "Get Open Purchase Orders" visible. Click → multi-select dialog of open POs filtered to that supplier. | |

---

## Section 11 — Document Reference Picker (commit `0ce0084`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 11.1 | Auto-prompt on type change | On a Payment References row, change Type from blank → **Purchase Invoice** | A `frappe.prompt` opens titled "Pick Purchase Invoice" with a Link field filtered to PIs of the PRF's company. | |
| 11.2 | Pick → fills both columns | In the prompt, select a PI like `PINV-AT-25-00056` | The Document Reference cell **and** the Invoice cell get populated with that PI name | |
| 11.3 | Manual = no prompt | Change Type to Manual | No prompt opens. User can type free text in Document Reference. | |
| 11.4 | No re-prompt when filled | On a row with Document Reference already populated, change Type → Purchase Order | No prompt fires (won't clobber the existing value). User can clear Document Reference manually first to re-pick. | |
| 11.5 | Company filter | When Type=Purchase Invoice on a PRF for `Avientek FZCO`, the prompt's Link options list only Avientek FZCO PIs | Verified | |

---

## Section 12 — Internal Transfer Party-Data Leak Fix (commit `676e798`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 12.1 | Switch Pay → Internal Transfer | New PRF: payment_type=Pay, party_type=Supplier, pick a Supplier with bank account + address. **Don't save.** Now switch payment_type → Internal Transfer | All party-side fields (party, party_name, party_bank_account, address_display, contact_display, contact_email, contact_mobile, supplier_balance) **clear automatically**. payment_references table empties. | |
| 12.2 | Save IT after switch | After 12.1, fill in Issued Bank + Receiving Bank + Amount. Save. | Saved Internal Transfer doc has **no** stale supplier address / contact data | |
| 12.3 | Reverse switch | New PRF: payment_type=Internal Transfer, fill banks. Switch to payment_type=Pay | Bank fields stay; party fields blank | |
| 12.4 | Submitted doc unaffected | Open a submitted PRF; verify payment_type can't be changed | Frappe blocks the change anyway | |

---

## Deploy verification (one-time after every Update + Migrate)

| Step | Detail |
|---|---|
| 1 | After Frappe Cloud Update + Migrate finishes, open Error Log → check no entries for "after_migrate: PV format sync failed" / "PRF self-approval block failed". |
| 2 | Run the smoke test: `bench --site avientekv21.frappe.cloud execute avientek.scripts.smoke_master.run` — expect "ALL 4 SUITES PASSED". |
| 3 | Open `/app/payment-request-form` list view as a non-admin user → verify list loads (no JS errors). |
| 4 | Open one PRF for each `payment_type` (Pay / Advance Pay / Internal Transfer / TR / LC) → verify form loads + Print works. |
| 5 | Verify the PRF workflow shows the right buttons for the test user's role. |
