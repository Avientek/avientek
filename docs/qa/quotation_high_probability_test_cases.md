# Quotation High-Probability Workflow — Manual Test Cases

Ship target: TEST system / `feature/quotation-high-prob` branch.
Pending **BRD signoff** before merging to master.

**Latest commit covered:** `1b6b2ce` (feature/quotation-high-prob, 2026-05-06).

---

## Setup — one-time per tester

### Roles required on the site

| Role | Purpose | Notes |
|---|---|---|
| `Sales support L2` | Quotation team / quote creator | Verify ≥1 user assigned |
| `GM-CS` | Quote Action Request — Level 1 approver | Verify ≥1 user assigned |
| `CS` | Quote Action Request — Level 2 approver | Verify ≥1 user assigned (audit on local showed **0** — assign before testing) |
| `Procurement L2` | Restricted — read-only on Approved+100 quotes | If the production role has a different name, set it via Avientek Settings → Restricted Roles table instead of creating |
| `System Manager` | Bypass everything | Standard |

Run `bench --site <site> execute avientek.scripts.check_quote_high_prob_roles.run` to audit existence + user counts.

### Test users

Create 5 disposable users for the matrix below. Each gets ONLY one of the roles above (plus `Sales User`/`Accounts User` so they can read Quotations at all):

| Test user | Roles |
|---|---|
| `qa.creator@example.com` | Sales User + **Sales support L2** |
| `qa.gmcs@example.com` | Sales User + **GM-CS** |
| `qa.cs@example.com` | Sales User + **CS** |
| `qa.procurement@example.com` | Sales User + **Procurement L2** |
| `qa.admin@example.com` | System Manager (bypass benchmark) |

### Test data

You'll need:
- 1 submitted Quotation with `probability = 50` (low-prob — used as control)
- 1 submitted Quotation with `probability = 80` (high-prob — locked)
- 1 submitted Quotation with `probability = 100, workflow_state = "Approved"` (the only one Restricted users should see)

---

## Section 1 — Avientek Settings configuration (commit `407e5fe`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 1.1 | New section visible | Open `/app/avientek-settings/Avientek Settings` | A new section "Quotation High-Probability Workflow" appears below the Reward & Incentive section | |
| 1.2 | Default L1 | Field "Quote Action Request — Level 1 Approver" | Default value `GM-CS` populated (placeholder shown if blank) | |
| 1.3 | Default L2 | Field "Quote Action Request — Level 2 Approver" | Default `CS` | |
| 1.4 | Default Creator | Field "Quotation Team Role" | Default `Sales support L2` | |
| 1.5 | Restricted Roles table | Field "Restricted Roles (Read-only on Approved+100)" | Empty by default. Add Row → `Procurement L2` → Save | |
| 1.6 | Save without errors | After 1.5, click Save | Saves cleanly. No JS errors in console. | |
| 1.7 | Form doesn't blank when child doctype missing | (Regression for `1b6b2ce`) Hard-refresh form after deploy before migrate | Form renders. No "Cannot read properties of undefined" error in console. | |

---

## Section 2 — Field Lock when probability ≥ 75 (commit `3922a31`)

### 2A — As `qa.creator@example.com` (Sales support L2)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 2A.1 | Low-prob editable | Open the prob=50 quote | Form fully editable. No banner. | |
| 2A.2 | Bumping prob 50 → 70 | Edit probability to 70, Save | Saves cleanly | |
| 2A.3 | Bumping prob 50 → 80 | Edit probability to 80, Save | Saves. **Now locked** on next refresh. | |
| 2A.4 | Locked banner | Reopen the now-prob=80 quote | Orange banner: "Quotation locked: probability 80% (>= 75%)…" | |
| 2A.5 | All fields read-only | Try to edit Customer / Items / Discount / Terms | All fields locked. No edit possible. | |
| 2A.6 | probability still editable | Click probability field | Field is editable | |
| 2A.7 | **Whitelist Action: 80 → 100** | Set probability to **100**, Save (no other field changes) | Saves successfully | |
| 2A.8 | 80 → 90 (intermediate) | Set probability to 90, Save | **Throws** — "Quotation locked… The only direct change permitted is bumping probability to exactly 100" | |
| 2A.9 | 80 → 100 with another change | Set probability to 100 AND change Terms field, Save | **Throws** — locked. Only probability=100 alone is allowed. | |
| 2A.10 | After-submit lock | Pull a submitted quote with prob=80; try `Edit` (Frappe's edit-after-submit on allowed fields) | Server's `on_update_after_submit` blocks any change other than the 100 bump | |

### 2B — As `qa.admin@example.com` (System Manager)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 2B.1 | Whitelist waiver banner | Open the prob=80 quote | **Yellow** banner: "Probability is 80% — high-prob lock waived for your role." | |
| 2B.2 | Free editing | Edit Customer + Terms, Save | Saves cleanly. No throw. | |
| 2B.3 | Cancel allowed | Run workflow Cancel action | Cancels (subject to standard ERPNext link checks) | |

### 2C — As `qa.gmcs@example.com` (GM-CS) and `qa.cs@example.com` (CS)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 2C.1 | Whitelist waiver | Open prob=80 quote | Yellow banner. Editable. | |
| 2C.2 | Sales support L2 too | Repeat 2C.1 as `qa.creator@example.com` | Yellow banner. Editable. (Sales support L2 is also whitelisted.) | |

---

## Section 3 — RBAC Visibility for Restricted Roles (commit `3922a31`)

### 3A — As `qa.procurement@example.com` (Procurement L2 only)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 3A.1 | Quotation list trimmed | Open Quotation list | Only quotes with `workflow_state='Approved' AND probability=100` are visible. The prob=50 and prob=80 quotes do NOT appear. | |
| 3A.2 | Quote Creator widening | If `qa.procurement` is the `owner` of a draft quote, that quote appears regardless of state | Visible | |
| 3A.3 | Parent Salesperson widening | If `qa.procurement` is mapped to a Sales Person that supervises a quote's Sales Team member | Quote visible | |
| 3A.4 | Direct URL | Try opening a non-Approved+100 quote by direct URL | Frappe blocks with "Insufficient Permission" | |
| 3A.5 | Report Builder | Build a custom Report Builder report on Quotation | Same filtering applies | |
| 3A.6 | API endpoint | `frappe.client.get_list({"doctype":"Quotation"})` from this user's session | Response only includes the permitted quotes | |

### 3B — As `qa.gmcs@example.com` (whitelist)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 3B.1 | Full list | Open Quotation list | All quotes visible (subject to existing brand/IG/sales-person UP) | |

### 3C — As `qa.admin@example.com`

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 3C.1 | Bypass | Open Quotation list | Everything visible | |

---

## Section 4 — Cancel Blocked on High-Prob Quote (commit `3922a31`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 4.1 | Direct Cancel blocked | As `qa.creator`, on a submitted prob=80 quote, click ERPNext's standard Cancel | **Throws** — "Cancel is blocked: this Quotation has probability 80% (>= 75%). Submit a Quotation Action Request (action=Cancel) and route it through Level 1 / Level 2 approval." | |
| 4.2 | Direct Cancel allowed for whitelist | As `qa.admin`, click Cancel on the same quote | Cancels (or fails on standard link checks if it has Sales Orders) | |
| 4.3 | Low-prob direct cancel | As `qa.creator`, on a submitted prob=50 quote, click Cancel | Cancels normally — no high-prob block | |

---

## Section 5 — Action Request UI Buttons on Quote (commit `f447066`)

### As `qa.creator@example.com` on a prob=80 submitted quote:

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 5.1 | Action Request button group | Look at the form's button bar | Group "Action Request" with three sub-buttons: "Request Cancel", "Request Amend", "Request Resubmit" | |
| 5.2 | Request Cancel dialog | Click "Request Cancel" | Dialog opens with a Reason text field (required) + "Submit Request" button | |
| 5.3 | Submit creates QAR | Enter reason "QA test", click Submit Request | Success toast: "Action Request QAR-2026-XXXXX created". Browser navigates to the new QAR form. | |
| 5.4 | QAR pre-filled | The new QAR form shows: quotation = the source quote, action = Cancel, current_probability = 80, current_workflow_state = (the source's state), workflow_state = Pending | All fields correct | |
| 5.5 | Duplicate prevention | Go back to the source quote, click "Request Cancel" again | Browser navigates to the **existing open** QAR (no new doc created) | |
| 5.6 | Buttons absent on low-prob | As same user, open prob=50 quote | "Action Request" button group is **not** rendered (high-prob lock didn't engage) | |
| 5.7 | Buttons absent for whitelist | As `qa.admin`, open prob=80 quote | Yellow waiver banner; no Action Request buttons (admin can use direct Cancel) | |

---

## Section 6 — Quotation Action Request Workflow End-to-End (commit `f447066`)

### Setup: Action Request `QAR-XXX` exists in Pending state from Section 5.

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 6.1 | Self-approval blocked at L1 | Login as **the same user** who created the QAR. Open the QAR. Try `Approve L1` | Frappe blocks: "Self-approval is not allowed" | |
| 6.2 | L1 by GM-CS | Login as `qa.gmcs@example.com` ; open the QAR ; click Approve L1 | State → `L1 Approved`. `level_1_approver` = qa.gmcs ; `level_1_approved_on` = current datetime | |
| 6.3 | L2 self-approval blocked | Same `qa.gmcs` clicks Approve L2 | Blocked (CS role required, not GM-CS) | |
| 6.4 | L2 by CS | Login as `qa.cs@example.com` ; click Approve L2 | State → `L2 Approved` for an instant; controller's `on_update` fires; the underlying quote's `cancel()` runs; State flips to `Executed`. `level_2_approver` = qa.cs ; `executed_on` populated ; `execution_log` shows "Cancelled Quotation QN-… via Action Request QAR-…" | |
| 6.5 | Underlying quote cancelled | Open the source Quotation | docstatus = 2 (Cancelled). | |
| 6.6 | Reject path | Create a new QAR. Login as `qa.gmcs` → Reject | State → `Rejected`. Source quote stays submitted (untouched). | |
| 6.7 | Reject from L1 Approved | New QAR → qa.gmcs Approve L1 → qa.cs Reject | State → `Rejected`. Source quote untouched. | |
| 6.8 | Amend action | Create a QAR with action = Amend on a fresh prob=80 submitted quote. Push through L1 + L2. | Source quote cancelled; a new draft Quotation created with `amended_from = <source>` ; QAR's `amended_quotation` field links to the new draft. State = Executed. | |
| 6.9 | Resubmit action | Same as 6.8 but action = Resubmit | Same outcome (Frappe doesn't have native resubmit — pattern is cancel+amend; the user re-submits the new draft from the form). | |

### Failure & rollback paths

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 6.10 | Linked SO blocks cancel | Pick a prob=80 quote that has a downstream Sales Order (`docstatus=1`). Push a Cancel QAR through L1 + L2. | The execution catches `LinkExistsError`. State stays `L2 Approved`. `execution_log` records the failure ("Execution failed: LinkExistsError…"). **Underlying quote stays submitted** (savepoint rollback). | |
| 6.11 | Manual retry | After 6.10, on the QAR set `executed_on = ''` and Save | controller's on_update sees the empty timestamp and re-fires the cancel attempt | |

---

## Section 7 — Avientek Settings Drives Live Config (commit `407e5fe`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 7.1 | Rename L1 role | Open Avientek Settings → change `Quote Action Request — Level 1 Approver` from `GM-CS` to `Finance Manager` (or any existing role) → Save | Saves cleanly | |
| 7.2 | Re-seed via migrate | Run `bench --site <site> migrate` | Migrate output: `[seed_quotation_action_request_workflow] workflow=… states=5 transitions=4 active=1` | |
| 7.3 | Workflow updated | Open Workflow `/app/workflow/Quotation Action Request Approval` | The "Approve L1" / "Reject (from Pending)" transitions now allowed for `Finance Manager` (the new role), not `GM-CS` | |
| 7.4 | Settings cache busts on save | Without restarting, refresh a Quotation form (prob=80 as `qa.creator`) | The whitelist banner / lock behaviour reflects the new role configuration | |
| 7.5 | Restricted role rename | Add another row in Restricted Roles table (e.g. `Sales User`) → Save | Sales Users now see only Approved+100 quotes (until row removed) | |
| 7.6 | Missing role fallback | Set L1 role to `Nonexistent Role XYZ` → Save → migrate | Seeder logs `WARN role 'Nonexistent Role XYZ' missing — skipping transition…` and the QAR workflow has fewer transitions until the role is created | |
| 7.7 | Empty restricted table | Clear all rows in Restricted Roles → Save | Restricted-role visibility filter no-ops; Procurement users (if any) see the standard ERPNext quote list | |

---

## Section 8 — Whitelisted Action: probability 75 → 100 (commit `3922a31`)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 8.1 | Exactly 100, no other changes | As `qa.creator` on prob=80 quote, change probability to 100 only, Save | Allowed. Quote saves. Subsequent open shows banner gone (now "won-state" — locked rules still apply at >=75 but probability=100 is the only change permitted) | |
| 8.2 | After 100, more locking | Try to edit Terms after 100 | Still locked (probability ≥ 75). Use Action Request flow. | |
| 8.3 | Drop below 75 not allowed via shortcut | As `qa.creator`, try to set probability from 80 to 60 directly | Saves NOT permitted by lock — only the 100 exception is allowed | |

---

## Deploy verification (one-time after every Update + Migrate on TEST)

| Step | Detail |
|---|---|
| 1 | Run `bench --site <site> execute avientek.scripts.check_quote_high_prob_roles.run` — every required role should show `OK` with ≥1 user assigned (especially CS for L2 approval). |
| 2 | Run `bench --site <site> execute avientek.scripts.smoke_quotation_high_prob.run` — expect `8/8 PASS`. |
| 3 | Run `bench --site <site> execute avientek.scripts.smoke_quotation_action_request.run` — expect `7/7 PASS`. |
| 4 | Open `/app/quotation-action-request` list view → verify list loads without errors. |
| 5 | Open `/app/workflow/Quotation Action Request Approval` → verify 5 states + 4 transitions, all `allow_self_approval=0`. |
| 6 | Open `/app/avientek-settings/Avientek Settings` → "Quotation High-Probability Workflow" section visible with the 4 fields. |

---

## Production cutover plan (after BRD signoff)

1. Merge `feature/quotation-high-prob` → `master` (squash or merge commit).
2. Frappe Cloud → Update + Migrate.
3. Open Avientek Settings on production → verify the L1/L2/Creator role names match production's actual role spellings (edit if not).
4. Add Restricted Roles rows for `Procurement L2` (or whatever the prod equivalent is).
5. Run smoke tests from "Deploy verification" section against production.
6. Communicate to users: high-probability quotes are now locked; use Action Request workflow for changes.
