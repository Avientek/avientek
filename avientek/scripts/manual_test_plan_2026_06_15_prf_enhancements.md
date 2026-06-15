# Manual Test Plan — PRF Enhancements 2026-06-15

Run this on prod **after the next Bench Update + `bench migrate`** completes.
Hard-refresh the browser once (Cmd+Shift+R / Ctrl+Shift+R) before starting so the new JS bundle loads.

Master tip: `e29355c` · Commits in this batch: `474ee54`, `f77a716`, `e29355c` · QuarkCS tasks: TSK-2026-00339 / 00340 / 00341

---

## Preconditions

- [ ] Login as a user with **Finance Controller** role (primary tester role) → needed for §1 + §3
- [ ] A second login available with **Sales User** (or any non-FC role) → needed for §3 negative test
- [ ] A third login as **System Manager** → needed for §3 break-glass case
- [ ] At least one PRF currently in `Approved Level 2` state (don't have one? Authorise → Approve L1 → Approve L2 a test PRF first)
- [ ] At least one PRF whose underlying Purchase Order chains through intercompany (PO → SO with `po_no` filled → Original SO → Quotation). If unsure which, ask Sridhar — only relevant for §2.

---

## §1 — "On Hold" workflow state (commit `f77a716`)

### Test 1.1 — Hold action visible on Approved Level 2

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open any PRF in `Approved Level 2` as **Finance Controller** | Form loads, workflow badge shows green "Approved Level 2" |
| 2 | Click the workflow action button (top-right) | Dropdown shows: **Hold**, Release Payment, Cancel |
| 3 | The Hold action SHOULD be visible — if not, check user has Finance Controller role | Pass = Hold visible |

### Test 1.2 — Click Hold transitions to On Hold

| Step | Action | Expected |
|------|--------|----------|
| 1 | Click **Hold** on the PRF from Test 1.1 | Confirmation dialog appears |
| 2 | Confirm the action | PRF saves; badge changes |
| 3 | Verify badge | Workflow badge shows **orange "On Hold"** (not red, not green) |
| 4 | Verify Action menu now | Dropdown shows: **Resume**, **Cancel** (Release Payment hidden) |

### Test 1.3 — Resume returns to Approved Level 2 (NOT directly to Released)

| Step | Action | Expected |
|------|--------|----------|
| 1 | On the On-Hold PRF, click **Resume** | Confirmation dialog |
| 2 | Confirm | Badge returns to **green "Approved Level 2"** |
| 3 | Verify Action menu | Dropdown shows: Hold, Release Payment, Cancel — same as Test 1.1 |
| 4 | **Critical**: the PRF must NOT auto-go to Released | If it goes to Released, regression — file ticket |

### Test 1.4 — Dashboard Number Card appears

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to the **Tasks** workspace | Workspace loads |
| 2 | Scroll to PRF number cards row | New card **"PRF On Hold"** is present alongside the existing 5 PRF cards |
| 3 | Verify the count | Count = number of PRFs currently in On Hold state (matches role-scope per Jithin's matrix) |
| 4 | Click the card | Should navigate to PRF list filtered by `workflow_state = "On Hold"` |

### Test 1.5 — Non-FC role cannot click Hold

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login as a user **without** Finance Controller role (e.g. Sales User, General Manager) | Login OK |
| 2 | Open any PRF in `Approved Level 2` | Form loads |
| 3 | Open the workflow action dropdown | **Hold** action is NOT visible (only the actions their role is allowed) |

### Test 1.6 — On Hold doc cannot be edited (matches Approved L2 lock)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open an On-Hold PRF as FC | All amount/line-item fields are read-only |
| 2 | Try to edit any amount or items row | Cannot — read-only |
| 3 | The 5 FC-editable fields (Issued Bank, Payment Mode, Cheque Date, Party Bank Account, Party Address) | Per §3 these are editable on Approved L2; behaviour on On Hold should be same — verify the orange FC banner still shows |

---

## §3 — Post-L2 FC edit + Release freeze + audit (commit `474ee54`)

### Test 3.1 — All 5 FC-editable pickers open on Approved Level 2

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open any PRF in `Approved Level 2` as **Finance Controller** | Form loads |
| 2 | Confirm orange FC banner at the top | Reads: *"You are authorised to update **Issued Bank**, **Payment Mode**, **Cheque Date**, **Party Bank Account**, and **Party Address**…"* |
| 3 | Click each of the 5 fields | Each opens a link picker / date picker — NOT read-only |
| 4 | All other amount/line/tax fields | Read-only |

### Test 3.2 — Edit each editable field, save, verify persisted

For each of the 5 fields, do:

| Step | Action | Expected |
|------|--------|----------|
| 1 | Change the value in the picker | Form marks itself "Not Saved" |
| 2 | Click Save (Ctrl+S) | Save succeeds with green toast |
| 3 | Refresh the page | New value persists |
| 4 | Open the Activity timeline (right sidebar gear → Activity, OR `Changes` tab) | Entry shows: `<user> updated <fieldname>: <old value> → <new value>` |

**Run this for all 5: Issued Bank, Payment Mode, Cheque Date, Party Bank Account (`supplier_bank_account`), Party Address (`supplier_address`).**

### Test 3.3 — Amount fields stay locked even for FC

| Step | Action | Expected |
|------|--------|----------|
| 1 | On the same Approved L2 PRF as FC, try to click on the Grand Total, any line item's amount, tax rows | Read-only — clicks do nothing |
| 2 | Try to add a row to the `Payment References` child table | Cannot — Add Row button hidden / grid frozen |

### Test 3.4 — Non-FC blocked from editing the 5 fields

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login as **Sales User** (or any non-FC role) | Login OK |
| 2 | Open the same Approved L2 PRF | Form loads but every field is read-only |
| 3 | Try to edit Issued Bank | Cannot — read-only |
| 4 | If somehow able to edit via API / dev console + Save | Server throws: *"Only Finance Manager or Finance Controller can change …"* |

### Test 3.5 — Release Payment freezes EVERYTHING

| Step | Action | Expected |
|------|--------|----------|
| 1 | On the Approved L2 PRF as FC, click **Release Payment** | Confirmation, then state → Released |
| 2 | Try to edit Issued Bank | Read-only |
| 3 | Try to edit Cheque Date | Read-only |
| 4 | Try to edit Party Bank Account | Read-only |
| 5 | Try to edit Party Address | Read-only |
| 6 | Try via API: `frappe.db.set_value("Payment Request Form", "<name>", "issued_bank", "Bank X")` from the developer console as FC | Server throws: *"Payment Request Form ... is in **Released** state — …  cannot be modified"* |
| 7 | The error message must mention the state (`Released`) and the field name | If the API call succeeds → regression, file ticket |

### Test 3.6 — System Manager break-glass works on Released

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login as **System Manager** | Login OK |
| 2 | Open the same Released PRF | Form loads — fields still UI-locked (apply_released_lock is global) |
| 3 | Via dev console / API: `frappe.db.set_value("Payment Request Form", "<name>", "issued_bank", "Bank X")` | Succeeds — System Manager bypass |
| 4 | Reload the form | New value persists |
| 5 | Activity timeline shows the SM edit with timestamp | Pass |

(System Manager bypass is intentional break-glass for genuine data correction. Document use cases in the audit ticket.)

### Test 3.7 — Audit trail captures everything

| Step | Action | Expected |
|------|--------|----------|
| 1 | Take any PRF where you made 2-3 field changes during Tests 3.2 and 3.6 | — |
| 2 | Open the form, click the gear menu → "Activity" OR scroll to bottom for the Changes section | A timeline of changes appears |
| 3 | Each change shows: who, when (timestamp), which field, old value, new value | If any of those 4 are missing — regression |
| 4 | Document Versions (Menu → Document Versions) also lists each version | Snapshot at each save persists |

---

## §2 — Quote traceability chain (commit `e29355c`)

### Test 2.1 — Standard (single-company) chain still works (regression guard)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open any PRF whose underlying Purchase Order chains to a Quotation **WITHOUT** intercompany hops (i.e. the PO's Sales Order was created directly from a Quotation) | Form loads |
| 2 | Print the PRF (use the standard Payment Voucher print format) | PDF / preview renders |
| 3 | Scroll to the **Brand Summary** section | Brand Summary table populates with rows from the linked Quotation — same as before this commit (no regression) |
| 4 | The "Connected Quotation: QN-xxx" header shows the same Quote name as before | Pass = no change in linked Quote |

### Test 2.2 — Intercompany chain now resolves (the new behaviour)

This is the **new value** of this commit. Need an intercompany PRF — ask Sridhar for an AVFZC-xxxx that pays an intercompany invoice.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open an intercompany PRF — one where the chain is PRF → PO → Linked SO → Original SO (via Linked SO's `po_no`) → Original Quote | Form loads |
| 2 | **Before this commit** the print would show NO Brand Summary section (because the Linked SO had no `prevdoc_docname`) | — historical baseline |
| 3 | Print the PRF after this commit | Brand Summary section **now appears** populated with rows from the Original Quotation |
| 4 | Verify the linked Quote name matches the ORIGINAL Quote (not anything from the intercompany side) | Pass = Original Quote name shown |
| 5 | Verify margin / incentive / cost columns populate from the Original Quote's Brand Summary child rows | Pass = data matches what the Original Quote shows in its own form |

### Test 2.3 — PRF with no chain doesn't show spurious Brand Summary

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open a PRF where the PO chain has NO Quotation anywhere (e.g. PO created from scratch, no SO link) | Form loads |
| 2 | Print the PRF | Brand Summary section is **absent / empty** — no fake rows, no `None` placeholder |

### Test 2.4 — Manual costing sheet attachment still respected

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open a PRF whose row has a `costing_sheet_attachment` filled in | Form loads |
| 2 | Print the PRF | The MANUAL costing sheet image is rendered; Brand Summary section is suppressed (per existing Rahul 2026-05-22 policy — manual sheet wins) |

---

---

## §4 — Quotation: one-click Cancel from Approved (commit `814cd44`)

QuarkCS task **TSK-2026-00343**. New behaviour: a margin-satisfied (Approved) Quotation can now be cancelled in **one click** by Sales Support L2, GM-CS, GM, or System Manager — bypassing the previous 2-level L1/L2 review chain. The old Request-Cancellation chain still exists for paper-trail cancellations.

### Test 4.1 — Direct Cancel visible to allowed roles on Approved

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open any Quotation in **Approved** state as **Sales Support L2** (or GM-CS, GM, System Manager) | Form loads |
| 2 | Click the workflow action button | Dropdown shows **Cancel** alongside the existing **Request Cancellation** |
| 3 | Repeat for each role (Sales Support L2 / GM-CS / GM / System Manager) | Cancel visible for all 4 |

Fails if Cancel is missing → check the user has one of the 4 allowed roles, and that `bench migrate` ran (`avientek.patches.add_quotation_direct_cancel_from_approved`).

### Test 4.2 — Click Cancel transitions directly to Cancelled

| Step | Action | Expected |
|------|--------|----------|
| 1 | From the Quotation in Test 4.1, click **Cancel** | Confirmation dialog |
| 2 | Confirm | Badge changes to **Cancelled** (red/grey) |
| 3 | Verify state | NO transit through Cancellation Requested or Cancellation L2 Pending — direct Approved → Cancelled |
| 4 | docstatus | Must be 2 |

Fails if Quotation has linked submitted Sales Orders → Frappe's standard guard blocks. Cancel the SOs first.

### Test 4.3 — Old Request-Cancellation chain still works (regression guard)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open another Approved Quotation as Sales Support L2 or GM-CS | Form loads |
| 2 | Click **Request Cancellation** (OLD path) | State → **Cancellation Requested** |
| 3 | Login as GM-CS, click **Approve Cancellation Level 1** | State → **Cancellation L2 Pending** |
| 4 | Login as GM, click **Approve Cancellation Level 2** | State → **Cancelled** |

This whole chain MUST still work. If any step fails → regression in the direct-cancel patch, file a ticket immediately.

### Test 4.4 — Non-allowed roles cannot see Cancel

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login as a user WITHOUT any of {Sales Support L2, GM-CS, GM, System Manager} (e.g. plain Sales User) | Login OK |
| 2 | Open any Approved Quotation | Form loads |
| 3 | Open workflow action dropdown | **Cancel** is NOT visible |

---

## Quick smoke (5-minute spot-check after deploy)

If you only have 5 minutes:

1. Open one Approved L2 PRF as FC → see Hold action in workflow menu ✓
2. Click Hold → see orange On Hold badge ✓
3. Click Resume → returns to green Approved L2 ✓
4. Change Issued Bank → save → reload → value persisted ✓
5. Open Activity timeline → see "X updated issued_bank: A → B" ✓
6. Click Release Payment → try to change Issued Bank → blocked with terminal-state error ✓
7. Tasks dashboard → PRF On Hold card visible ✓
8. Open one PRF Voucher print → Brand Summary still renders (no regression) ✓
9. Open one Approved Quotation as Sales Support L2 → click **Cancel** → state goes directly to Cancelled (one shot) ✓

If all 8 pass: **deploy is healthy**. If any fail, capture screenshot + PRF name + commit hash and ping me.

---

## Common pitfalls

- **Bench Update didn't run yet** — the JS won't be the new version. Look for "Party Bank Account" and "Party Address" in the FC banner; if you only see "Issued Bank, Payment Mode, Cheque Date" the deploy didn't complete.
- **Browser cache** — hard-refresh once (Cmd+Shift+R). The `?v=1` cache-bust on yesterday's `number_card_click_fix.js` is the same pattern but THIS deploy doesn't bump the JS cache key for `payment_request_form.js`; the doctype JS is reloaded via Frappe's normal asset versioning.
- **`bench migrate` didn't run** — patches won't apply: §1 won't have the workflow state, §3 won't have `supplier_address.allow_on_submit=1`. Frappe Cloud's deploy runs migrate automatically; self-hosted needs `bench --site <site> migrate` after Bench Update.
- **Role missing on a test user** — Hold won't show, the FC banner won't appear. Verify roles via User Permission Manager.

---

## If something is broken

1. **Capture**: PRF name + screenshot of the issue + your Chrome DevTools console (any JS errors) + the workflow_state badge text + your role list.
2. **Report**: WhatsApp to me with the captures + commit hash (`e29355c` / `f77a716` / `474ee54`).
3. **Workaround**: System Manager can override everything via Frappe API. Use sparingly + log the reason for the audit trail.
