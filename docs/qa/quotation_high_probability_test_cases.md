# Quotation High-Probability + Document Approval — Manual Test Cases

Ship target: production after smoke + UAT signoff.

**Latest commit covered:** V3 redesign (Rahul/Sridhar 2026-05-08) — replaces the QAR 2-level approval with the Sales-Order-style Document Approval pattern on Quotation itself.

---

## Setup — one-time per tester

### Roles required on the site

> **High-prob roles are configured dynamically via Avientek Settings → "Quotation High-Probability Workflow"**. The names below are the **defaults** that ship with the app and act as a fallback when the corresponding Avientek Settings field is blank. To rename or reassign a role on a site, just edit Avientek Settings and Save — no code change. The workflow seeder re-reads the config on every migrate.

| Avientek Settings field | Default role | Purpose | Notes |
|---|---|---|---|
| `Quotation Team Role` | `Sales support L2` | Quote creators — file Document Approval requests | Verify ≥1 user assigned |
| `Quote Approval Role` | `CS` | Single approver who decides on Request for Update / Cancellation Check / Send for Approval transitions | Verify ≥1 user assigned. Cannot self-approve. |
| `Restricted Roles` (child table) | `Procurement L2` | Read-only on Approved + probability=100 quotes | Add/replace rows in the table on the site; the listed role(s) just need to exist |
| `System Manager` (built-in) | — | Bypass everything | Standard, not configured |

Run `bench --site <site> execute avientek.scripts.check_quote_high_prob_roles.run` to audit existence + user counts (resolves live values from Avientek Settings).

### Test users

Create 4 disposable users for the matrix below. Each gets ONLY one of the roles above (plus `Sales User` so they can read Quotations at all):

| Test user | Roles |
|---|---|
| `qa.creator@example.com` | Sales User + **Sales support L2** |
| `qa.approver@example.com` | Sales User + **CS** |
| `qa.procurement@example.com` | Sales User + **Procurement L2** |
| `qa.admin@example.com` | System Manager (bypass benchmark) |

### Test data

You'll need:
- 1 submitted Quotation with `probability = 50` (low-prob — used for inline-edit test)
- 1 submitted Quotation with `probability = 80` (high-prob — locked, used for Document Approval flow)
- 1 submitted Quotation with `probability = 100, workflow_state = "Approved"` (visible to Restricted users)

---

## Section 1 — Avientek Settings configuration

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 1.1 | Settings section visible | Open `/app/avientek-settings/Avientek Settings` | "Quotation High-Probability Workflow" section visible | |
| 1.2 | Default Quote Approval Role | Field "Quote Approval Role" | Default `CS` populated (placeholder shown if blank) | |
| 1.3 | Default Quotation Team Role | Field "Quotation Team Role" | Default `Sales support L2` | |
| 1.4 | Restricted Roles table | "Restricted Roles (Read-only on Approved+100)" | Empty by default. Add Row → `Procurement L2` → Save | |
| 1.5 | Save without errors | After 1.4, click Save | Saves cleanly. No JS errors in console | |
| 1.6 | Form doesn't blank when child doctype missing | Hard-refresh form after deploy before migrate | Form renders. No "Cannot read properties of undefined" error in console | |

---

## Section 2 — Field Lock when probability ≥ 75

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 2.1 | Sales rep blocked from inline edit | As `qa.creator`, open submitted prob=80 quote, change rate on a row, Save | Server throws "This Quotation is locked because probability ≥ 75". Save fails. Error mentions "Document Approval section" | |
| 2.2 | Whitelist 75→100 bump allowed | Same user, set probability=100 only (no other field), Save | Allowed (Whitelist Action) | |
| 2.3 | System Manager bypass | As `qa.admin`, change rate on locked quote | Allowed | |
| 2.4 | Approver bypass | As `qa.approver` (CS), change rate on locked quote | Allowed (CS is in whitelist) | |

---

## Section 3 — RBAC Visibility for Restricted Roles

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 3.1 | Restricted user sees only Approved+100 | As `qa.procurement`, open Quotation list | Only quotes with `workflow_state='Approved' AND probability=100` visible. Lower-prob and non-Approved quotes hidden | |
| 3.2 | Direct URL block | Try opening a non-Approved+100 quote by direct URL | "Insufficient Permission" | |
| 3.3 | Owner widening | If `qa.procurement` is `owner` of any draft quote | Visible (owner widening kicks in) | |
| 3.4 | Whitelist roles see all | As `qa.approver` or `qa.admin`, open Quotation list | All quotes visible | |
| 3.5 | API filtering | `frappe.client.get_list({"doctype":"Quotation"})` from `qa.procurement` session | Response only has permitted quotes | |

---

## Section 4 — Cancel Blocked on High-Prob Quote

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 4.1 | Direct cancel blocked | As `qa.creator`, click Menu → Cancel on prob=80 submitted quote | Throw "Cancel is blocked: probability 80%. Tick Cancellation Check in the Document Approval section" | |
| 4.2 | Whitelist users still allowed | As `qa.admin`, do the same direct cancel | Allowed (admin override) | |

---

## Section 5 — Document Approval Flow: Request for Update (NEW)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 5.1 | Document Approval section visible | As `qa.creator`, open submitted prob=80 quote → scroll down | "Document Approval" section visible with two checkboxes (Request for Update, Cancellation Check) | |
| 5.2 | Section hidden on low-prob quote | Same user, open submitted prob=50 quote | Document Approval section NOT visible (depends_on `probability>=75`) | |
| 5.3 | Section hidden on draft | Open a draft quote | Section NOT visible (depends_on `docstatus==1`) | |
| 5.4 | Tick Request for Update without note | Tick checkbox + try to Save (don't fill Revision Note) | Save fails: "Revision Note is mandatory" | |
| 5.5 | Tick + fill note + Save | Tick, fill Revision Note ("Customer requested 5% discount"), Save | Save succeeds. workflow_state moves to "Requested for update" | |
| 5.6 | Approver sees the request | Login as `qa.approver`, open the quote | Workflow buttons "Approve" and "Reject Update" visible at the top | |
| 5.7 | Approver approves the request | Click "Approve" | workflow_state moves to "Approved for Update". Quote is now editable | |
| 5.8 | Creator can now edit | Login as `qa.creator`, change a row's rate, Save | Save succeeds (no lock — workflow_state is "Approved for Update") | |
| 5.9 | Send for Approval | Click "Send for Approval" workflow button | workflow_state moves to "Pending For Approval" | |
| 5.10 | Approver final approves | As `qa.approver`, click "Approve" | workflow_state moves to "Approved". Quote re-locked at high-prob lock | |
| 5.11 | Approver self-approval blocked | If `qa.approver` was the user who ticked Request for Update on step 5.5 | "Approve" button hidden — self-approval blocked | |

---

## Section 6 — Document Approval Flow: Cancellation Check (NEW)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 6.1 | Tick Cancellation Check | As `qa.creator`, on submitted prob=80 quote → tick Cancellation Check, fill Cancellation Reason, Save | workflow_state moves to "Cancellation Requested" | |
| 6.2 | Approver decides | As `qa.approver`, click "Approve Cancellation" | docstatus moves to 2 (Cancelled). Source quote is now Cancelled | |
| 6.3 | Reject Cancellation path | Reset to a fresh prob=80 quote → repeat 6.1, then approver clicks "Reject Cancellation" | workflow_state goes back to "Approved". Source quote unchanged | |
| 6.4 | Withdraw cancellation request | After 6.1, as `qa.creator`, untick Cancellation Check + Save | "Cancel Request" transition fires automatically (condition `not doc.custom_cancellation_check`). workflow_state goes back to "Approved" | |

---

## Section 7 — Whitelisted Action: probability 75 → 100

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 7.1 | Inline 75→100 bump | As `qa.creator`, on submitted prob=75 quote, change probability to 100 (no other field), Save | Allowed. Probability now 100 | |
| 7.2 | 75→100 with another field change | Set probability=100 AND change rate, Save | Save fails: "only direct change permitted is bumping probability" | |
| 7.3 | 75→other (not 100) blocked | Set probability=80, Save | Blocked — only 100 is the whitelist target | |

---

## Section 8 — Inline edit on submitted <75% quotes

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 8.1 | Probability inline edit | As `qa.creator`, on submitted prob=50 quote, change probability to 60, Save | ✅ Save succeeds (allow_on_submit on probability) | |
| 8.2 | Other field inline edit | Same quote, try to change tc_name, Save | ❌ "Edit Restricted: only the Probability field can be updated inline" | |
| 8.3 | Bump into lock zone | Change probability from 50 to 80, Save | ✅ Save succeeds. Subsequent edits go through Document Approval flow | |

---

## Section 9 — Special Prices Carve-out (NEW — Rahul rule)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 9.1 | Update special price on locked quote | As `qa.creator`, on submitted prob=80 quote, edit one row's `custom_special_price`, Save | ✅ Save succeeds (special-price carve-out) | |
| 9.2 | Update standard price on locked quote | Same quote, edit a row's standard `rate`, Save | ❌ Lock fires — must use Document Approval flow | |
| 9.3 | Mixed change (special + standard) | Edit special_price AND rate on the same row, Save | ❌ Lock fires (carve-out only when ONLY special-price changed) | |

---

## Section 10 — Probability 100 Notification (NEW)

| # | Test | Steps | Expected | Result |
|---|---|---|---|---|
| 10.1 | Notification fires on transition | On prob=80 submitted quote, change probability to 100, Save | Email sent to: doc.owner + Sales Team users + users with `Quote Approval Role`. Subject: "Quotation X reached 100% probability" | |
| 10.2 | No re-notification on idempotent save | Save again at prob=100 (no change) | No new email sent (transition guard) | |
| 10.3 | No notification on bump from 100 to 100 inline | (idempotent test) | No email | |

---

## Smoke commands (run on test/prod)

```bash
# 5-suite master smoke
bench --site <site> execute avientek.scripts.smoke_master.run

# Document Approval V3 smoke (new — replaces QAR smoke)
bench --site <site> execute avientek.scripts.smoke_quotation_document_approval.run

# Field-lock + RBAC + inline-bump smoke
bench --site <site> execute avientek.scripts.smoke_quotation_high_prob.run

# Role audit (resolves live from Avientek Settings)
bench --site <site> execute avientek.scripts.check_quote_high_prob_roles.run

# Diagnostic if you need to verify QAR removal completeness on a stale site
bench --site <site> execute avientek.scripts.diag_high_prob_residue.run
```

---

## Rollback

If the V3 deploy breaks something, instant rollback is two SQL commands:

```python
# In Frappe Cloud System Console
import frappe
frappe.db.set_value("Workflow", "Quotation Approval Workflow Avientek (V3)", "is_active", 0)
# Re-activate whichever V2 was previously active (e.g. "Quotation Approval Workflow Avientek (V2)")
frappe.db.set_value("Workflow", "Quotation Approval Workflow Avientek (V2)", "is_active", 1)
frappe.db.commit()
frappe.clear_cache()
```

V2 stays in the database as `is_active=0` after the V3 seeder runs, so this rollback is non-destructive.

---

## Known carryovers from earlier rounds

- Inline 75→100 probability bump (commit `c60bc55`, 2026-05-07) — **kept** in V3
- Sales Order Optional Items leak fix (commit `0ded08e`, 2026-05-07) — **independent**, still applies to "Get Items From Quotation" flow
- Signature Images on PV Fast/Pro (commit `f05f465`, 2026-05-08) — **independent**, no relation to high-prob
- PRF self-approval banner (commit `a8d9c8d`, 2026-05-08) — **independent**, applies to Payment Request Form only
