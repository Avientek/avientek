# Manual UI Test Plan — Reward & Incentive JV Booking

**Feature**: Avientek Settings → "Reward & Incentive JV Booking" — auto-creates a Journal Entry on Sales Invoice submit that posts the reward and incentive amounts (from the source Quotation) into the right expense + payable accounts per company.

**Code locations**:
- Logic: `avientek/events/sales_invoice_reward_incentive.py`
- Settings: Avientek Settings → child table `Avientek Reward Incentive Account`
- Trigger: Sales Invoice `on_submit` + `on_cancel`

**Investigation date**: 2026-06-15

---

## Behaviour summary (for the tester)

When a Sales Invoice is **submitted**, the system:
1. Looks up `Avientek Settings.reward_incentive_method` (either **Quotation Wise** or **Item Wise**)
2. Looks up the company-account mapping for `SI.company` (Reward Expense / Reward Payable / Incentive Expense / Incentive Payable accounts)
3. Traces the source **Quotation** by walking SI Item → Sales Order Item → `prevdoc_docname`
4. Computes the reward + incentive amounts (see formulas below)
5. Posts a Journal Entry:
   - **Dr** Reward Expense Account (per company)
   - **Dr** Incentive Expense Account (per company)
   - **Cr** Reward Payable Account (per company, reference = source Quote)
   - **Cr** Incentive Payable Account (per company, reference = source Quote)
6. Saves the JV name on `SI.custom_reward_incentive_jv` for audit

### Formulas

**Quotation Wise** (default):
```
proportion = SI.grand_total / Quote.grand_total
reward     = Quote.custom_total_reward_new   × proportion
incentive  = Quote.custom_total_incentive_new × proportion
```

**Item Wise**:
```
for each SI item:
    matching Quote item (by item_code)
    proportion = min(si_item.qty / quote_item.qty, 1.0)
    reward    += quote_item.reward × proportion
    incentive += quote_item.custom_incentive_value × proportion
```

### Skip conditions (NO JV created)

The system silently skips JV booking AND adds a Comment on the SI for audit when:
- SI is a return (`is_return = 1`)
- `custom_reward_incentive_jv` is already populated (no double booking on re-submit)
- No Quote can be traced from SI Items
- Avientek Settings missing the method or the company-account mapping
- Computed reward + incentive are **both zero**

---

## Preconditions (do before any test)

- [ ] Avientek Settings → **Reward & Incentive Method** set to either "Quotation Wise" or "Item Wise"
- [ ] Avientek Settings → **Company Account Mapping** table has at least one row for the company you're testing against, with all 4 accounts filled (Reward Expense / Reward Payable / Incentive Expense / Incentive Payable)
- [ ] A Quotation exists with non-zero `custom_total_reward_new` and/or `custom_total_incentive_new`
- [ ] That Quotation has a chain to a Sales Invoice (Quote → SO → SI)

---

## §A — Setup verification (run once)

### Test A.1 — Method configured
| Step | Action | Expected |
|---|---|---|
| 1 | Open Avientek Settings | Form loads |
| 2 | Scroll to "Reward & Incentive JV Booking" section | Section visible |
| 3 | Verify "Reward & Incentive Method" field | Set to either "Quotation Wise" or "Item Wise" (not blank) |

### Test A.2 — All 6 Avientek companies mapped
| Step | Action | Expected |
|---|---|---|
| 1 | In the "Company Account Mapping" table, verify rows exist for: Avientek FZCO, Avientek Electronics Trading PVT. LTD, Avientek Trading W.L.L, AVIENTEK TRADING LLC, plus any other active Avientek entity | Row per company |
| 2 | Each row has all 4 accounts filled | Reward Expense, Reward Payable, Incentive Expense, Incentive Payable — no blanks |
| 3 | Reward Expense accounts are P&L accounts (Expense type) | Confirmed by clicking the account, root_type = "Expense" |
| 4 | Reward Payable accounts are Balance Sheet accounts (Liability type) | Confirmed by clicking, root_type = "Liability" |

---

## §B — Quotation Wise method (happy path)

Set Avientek Settings → Reward & Incentive Method = **Quotation Wise**.

### Test B.1 — Full Quote → full SI = full reward + incentive
| Step | Action | Expected |
|---|---|---|
| 1 | Pick a Quotation QN-xxx with reward=100, incentive=50, grand_total=1000 | Note the values |
| 2 | Create + submit a Sales Order for the FULL quote (grand_total=1000) | SO submitted |
| 3 | Create + submit a Sales Invoice for the FULL SO (grand_total=1000) | SI submitted |
| 4 | Open the SI form → scroll to "Reward Incentive JV" field | Field populated with a JV name like ACC-JV-xxx |
| 5 | Click the JV link → open the JV | JV loads, docstatus=Submitted |
| 6 | Verify JV lines: Dr Reward Expense 100, Dr Incentive Expense 50, Cr Reward Payable 100, Cr Incentive Payable 50 | All 4 lines present, totals balance |
| 7 | Verify JV user_remark | Mentions both SI name and source Quote name |

### Test B.2 — Partial SI (50%) → half reward + incentive
| Step | Action | Expected |
|---|---|---|
| 1 | Pick a Quotation with reward=100, incentive=50, grand_total=1000 | Note values |
| 2 | Create + submit a SO + SI for HALF the quote (grand_total=500) | SI submitted |
| 3 | Open the JV from `custom_reward_incentive_jv` | JV loads |
| 4 | Verify reward = 50, incentive = 25 (proportional to 500/1000 = 0.5) | Lines match the half |

### Test B.3 — JV references the Quotation
| Step | Action | Expected |
|---|---|---|
| 1 | Open the JV created in Test B.1 | Form loads |
| 2 | Verify the Cr (payable) lines have `reference_type=Quotation`, `reference_name=QN-xxx` | Both payable rows reference the source Quote |

---

## §C — Item Wise method

Switch Avientek Settings → Reward & Incentive Method = **Item Wise**, save.

### Test C.1 — Partial-qty SI → per-item proportional reward
| Step | Action | Expected |
|---|---|---|
| 1 | Pick a multi-item Quotation. Item A: qty=10, reward=20, incentive=10. Item B: qty=5, reward=15, incentive=5 | Note values per item |
| 2 | Create + submit a SO + SI invoicing only 4 of Item A and 5 of Item B | SI submitted |
| 3 | Open the JV from the SI | JV loads |
| 4 | Verify reward = (4/10 × 20) + (5/5 × 15) = 8 + 15 = **23** | JV reward matches |
| 5 | Verify incentive = (4/10 × 10) + (5/5 × 5) = 4 + 5 = **9** | JV incentive matches |

### Test C.2 — Over-invoicing capped at 100%
| Step | Action | Expected |
|---|---|---|
| 1 | Take a Quote with Item A qty=10, reward=20 | Note |
| 2 | Create + submit an SI invoicing 12 of Item A (somehow — usually requires multiple deliveries or override) | SI submitted |
| 3 | Verify JV reward = 20 (not 24) | Proportion capped at 1.0 |

---

## §D — Skip conditions (NO JV expected)

### Test D.1 — Return invoice (is_return=1) → No JV
| Step | Action | Expected |
|---|---|---|
| 1 | Create a return SI (is_return=1) | SI loads |
| 2 | Submit the return SI | Submits OK |
| 3 | Open SI form, scroll to `custom_reward_incentive_jv` | Field is EMPTY |
| 4 | Open the SI's Comments section | Comment present: "is_return — no JV booked" |

### Test D.2 — SI without linked Quote → No JV
| Step | Action | Expected |
|---|---|---|
| 1 | Create a Sales Invoice directly (no SO, no Quote chain — manually pick items) | SI loads |
| 2 | Submit | Submits OK |
| 3 | `custom_reward_incentive_jv` field | EMPTY |
| 4 | SI Comments | "no Quotation traceable from Sales Invoice items — JV skipped" |

### Test D.3 — Zero reward + zero incentive → No JV
| Step | Action | Expected |
|---|---|---|
| 1 | Take a Quote with reward=0 and incentive=0 | Note |
| 2 | Submit an SI from that Quote (via SO chain) | SI submits |
| 3 | `custom_reward_incentive_jv` | EMPTY |
| 4 | SI Comments | "computed reward=0 + incentive=0 both zero — JV skipped" |

### Test D.4 — Re-submit after amend → no double JV
| Step | Action | Expected |
|---|---|---|
| 1 | From the SI in Test B.1 (already has a JV booked), Cancel + Amend the SI | SI duplicated as -1 |
| 2 | Submit the amended SI | Submits OK |
| 3 | Open amended SI's `custom_reward_incentive_jv` | Either EMPTY (because old JV was cancelled, new flow starts fresh) OR populated with a NEW JV (depending on whether old SI is_amended_from picks up old JV ref) |
| 4 | **Critical**: there must NOT be 2 active JVs against the same SI chain | Only the latest valid JV is Submitted |

---

## §E — Cancel SI cancels the JV

### Test E.1 — Cancel SI → JV auto-cancelled
| Step | Action | Expected |
|---|---|---|
| 1 | Take a Submitted SI with a JV booked (`custom_reward_incentive_jv` populated) | Note both names |
| 2 | Cancel the SI | Cancels successfully |
| 3 | Open the JV | docstatus = 2 (Cancelled) |
| 4 | Re-open the SI | `custom_reward_incentive_jv` field is now EMPTY |
| 5 | Check SI Comments | New comment: "Cancelled reward/incentive JV ACC-JV-xxx" |

### Test E.2 — Cancel SI where JV was manually deleted earlier
| Step | Action | Expected |
|---|---|---|
| 1 | Take an SI with a JV booked. Manually delete the JV directly via dev console (simulates a data corruption) | JV deleted from DB |
| 2 | Cancel the SI | Should still cancel cleanly (no crash) |
| 3 | `custom_reward_incentive_jv` field still references the deleted JV name | Acceptable — the code does `frappe.db.exists` before attempting cancel |
| 4 | Check Error Log | No errors logged |

---

## §F — GL Impact verification

### Test F.1 — Reward Expense account hit per company
| Step | Action | Expected |
|---|---|---|
| 1 | Submit SI as Avientek FZCO → JV books to FZCO's Reward Expense account from Settings | Dr line on `4-01-02-22 - Reward...` (or whichever is mapped) |
| 2 | Repeat for Avientek Electronics Trading PVT. LTD | Dr line on the AETPL Reward Expense account |
| 3 | Verify each company posts to ITS OWN mapped accounts (no cross-company leakage) | Each JV uses the row matching `SI.company` |

### Test F.2 — Cost center on JV
| Step | Action | Expected |
|---|---|---|
| 1 | Open an SI with a cost_center set | Note the cost_center |
| 2 | Submit + open the booked JV | JV lines all carry the same cost_center as the SI |

### Test F.3 — JV is_opening = 'No'
| Step | Action | Expected |
|---|---|---|
| 1 | Open any booked JV | `is_opening` should be "No" (standard JV, not opening balance) |

---

## §G — Negative tests (configuration breakage)

### Test G.1 — Method not set → SI submits without crashing, no JV
| Step | Action | Expected |
|---|---|---|
| 1 | In Avientek Settings, blank out the "Reward & Incentive Method" field, save | Saved |
| 2 | Submit any SI from a Quote with reward | SI submits |
| 3 | `custom_reward_incentive_jv` field | EMPTY |
| 4 | SI Comments | A "settings missing" comment |
| 5 | Error Log | No errors |
| 6 | Restore method to "Quotation Wise" before next tests | Done |

### Test G.2 — Company mapping missing → SI submits, no JV
| Step | Action | Expected |
|---|---|---|
| 1 | Remove the mapping row for one company (e.g. Avientek Trading W.L.L) | Save |
| 2 | Submit an SI for that company | SI submits without crashing |
| 3 | `custom_reward_incentive_jv` | EMPTY |
| 4 | SI Comments | Note about missing account mapping |
| 5 | Restore the mapping row before next tests | Done |

---

## Quick smoke (3-minute spot-check)

1. Open Avientek Settings → confirm Reward Method + 6 company mappings ✓
2. Submit one full-Quote → full-SI → JV is created, balanced ✓
3. Open the JV → Dr+Cr balance, references the Quote ✓
4. Cancel the SI → JV auto-cancels, SI field clears ✓

If all 4 pass: **feature is healthy**.

---

## What to report back

For every FAIL: capture
- SI name + Quote name + JV name
- Avientek Settings screenshot (Method + the company row used)
- The JV's GL preview screenshot
- The SI's Comments section screenshot (skip-reason comments)
- Frappe Error Log (if any)

Send to Sammish on WhatsApp with the test number (B.2, D.3 etc) that failed.
