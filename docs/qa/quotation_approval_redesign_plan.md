# Quotation Approval Redesign — Plan

**Status**: Draft for Sridhar / Rahul / Jithin / Manu review
**Date**: 2026-05-09
**Replaces**: Quotation Action Request (QAR) doctype + 2-level approval workflow (shipped 2026-05-07 in commits `eb20e7d` / `c60bc55`)
**Mirrors**: existing Sales Order "Document Approval" pattern + `Sales Order Updated` workflow

---

## Why we're redoing this

QAR (the 2-level approval flow we shipped) is too restrictive. Sales team rejected it. Rahul's WhatsApp 2026-05-08 + meeting record confirms the new rules:

### Rule 1 — Quotes with probability ≥ 75%
- All revisions restricted **except** changing probability itself (75 → 100)
- Mandatory approval before Cancellation / Amendment / Resubmission
- Approval is **single-level** (not 2-level QAR), via existing Approval workflow

### Rule 2 — Quotes with probability < 75%
- Standard workflow — Sales / Sales Support can Cancel / Amend / Resubmit **without** approval, **if** all workflow conditions are met
- If any workflow condition is not met → routed to approval

### Rule 3 — Special Prices (Rahul's note)
- Updates to `custom_special_price` should NOT be subject to high-prob lock
- Even on submitted quotes, special prices remain editable inline (allows necessary discounts)

### Rule 4 — Notification on 100%
- When probability reaches 100, fire a notification (per meeting record)

---

## Sales Order pattern we will mirror

The SO "Document Approval" pattern already exists on production. It uses 4 custom fields + 1 workflow:

### SO Custom Fields

| Fieldname | Label | Type | Notes |
|---|---|---|---|
| `custom_document_approval` | Document Approval | Section Break | container |
| `custom_request_for_update` | Request for Update | Check | user ticks to ask for edit access |
| `custom_cancellation_check` | Cancellation Check | Check | user ticks to ask for cancellation |
| `custom_revision_note` | Revision Note | Small Text | `mandatory_depends_on='eval:doc.custom_request_for_update'` |
| `custom_cancellation_reason` | Cancellation Reason | Small Text | similar — for cancellations |

### SO Workflow: `Sales Order Updated`
- 11 states, 23 transitions
- Single-level approval role: **Supply Chain Head**
- Transitions gated by checkbox conditions (`doc.custom_request_for_update`, `doc.custom_cancellation_check`)

States used:
```
Draft → Submitted ───┬─→ Requested for update ─→ Approved for Update ─→ Pending For Approval ─→ Approved
                     │                                                              │
                     │                                                              ├─→ Cancelled
                     │                                                              └─→ Sent for Revision (loop)
                     └─→ Cancellation Requested ─→ Cancellation Approved → Cancelled
```

---

## Quotation Approval — proposed design

### Approval role for Quotation
Mirroring the SO pattern, the approver role on Quotation should be a **single role** (not 2-level). Suggested options:

| Approver role | Pros | Cons |
|---|---|---|
| `CS` | Already exists; matches current high-prob L2 role | CS team owns daily ops; might be a bottleneck |
| `GM-CS` | Existing high-prob L1 role | Same — owns daily ops |
| Sales Manager (new role) | Dedicated approver | Need to create + assign users |
| `CS` + `GM-CS` (either) | Two paths to approval — low bottleneck | Slight ambiguity |

**Recommended**: keep it driven by Avientek Settings — add a new field `quote_approval_role` (Link to Role) with default `CS`. Same dynamic-role pattern as the QAR roles. Renaming or reassigning is a single Avientek Settings edit.

### Custom fields to add on Quotation

Mirror SO 1-for-1 (with `custom_` prefix):

| Fieldname | Label | Type | Depends on / Mandatory |
|---|---|---|---|
| `custom_document_approval` | Document Approval | Section Break | depends_on `eval:doc.docstatus==1 && doc.probability>=75` |
| `custom_request_for_update` | Request for Update | Check | (visible same as section) |
| `custom_cancellation_check` | Cancellation Check | Check | (visible same as section) |
| `custom_revision_note` | Revision Note | Small Text | `mandatory_depends_on='eval:doc.custom_request_for_update'` |
| `custom_cancellation_reason` | Cancellation Reason | Small Text | `mandatory_depends_on='eval:doc.custom_cancellation_check'` |

The `depends_on` on the section ensures the whole block is **invisible for low-prob (<75%) quotes** — Rule 2 (sales team edits freely there).

### New Quotation workflow states

Extend existing `Quotation Approval Workflow Avientek (V2)` (currently active on prod) with these additional states:

| State | doc_status | Role allowed to edit |
|---|---|---|
| `Requested for update` | 1 | All (creator) |
| `Approved for Update` | 1 | All (so the original creator can now edit) |
| `Pending For Approval` | 1 | All (read-only; waiting for approver) |
| `Cancellation Requested` | 1 | All |
| `Cancellation Approved` | 1 | (approver only) |
| `Sent for Revision` | 1 | All |

(`Approved`, `Submitted`, `Cancelled` already exist in V2.)

### New transitions on Quotation workflow

Mirror SO 1-for-1, but gated on probability:

| From | Action | To | Role | Condition |
|---|---|---|---|---|
| `Approved` | Request for Update | Requested for update | All (creator) | `doc.custom_request_for_update && doc.probability>=75` |
| `Approved` | Request Cancellation | Cancellation Requested | All (creator) | `doc.custom_cancellation_check && doc.probability>=75` |
| `Requested for update` | Approve | Approved for Update | (approver) | — |
| `Requested for update` | Reject Update | Approved | (approver) | — |
| `Approved for Update` | Send for Approval | Pending For Approval | All | — |
| `Pending For Approval` | Approve | Approved | (approver) | — |
| `Pending For Approval` | Reject | Sent for Revision | (approver) | — |
| `Cancellation Requested` | Approve Cancellation | Cancelled | (approver) | — |
| `Cancellation Requested` | Reject Cancellation | Approved | (approver) | — |
| `Sent for Revision` | Send for Approval | Pending For Approval | All | — |

(Plus self-cancel transitions if user un-ticks the checkbox.)

### Special Prices carve-out (Rahul Rule 3)

Add to allow_on_submit on `Quotation Item`:
- `custom_special_price`
- `custom_special_rate`
- `custom_special_price_note`
- `custom_addl_discount_amount`

These fields will remain editable on the row even when the parent Quotation is locked. Server-side validator (`enforce_high_prob_lock_on_save`) will be relaxed: if **only** these fields changed on **only** the items table, allow the save without going through workflow.

### Probability 75 → 100 inline bump (already shipped today via `c60bc55`)

This stays as-is. `Quotation.probability` field has `allow_on_submit=1` Property Setter. Validator `on_update_after_submit` allows the bump when only probability changed.

### 100% probability notification (Rule 4)

Add a `Notification` doctype record (Frappe-native, not custom code) on Quotation:
- Trigger: `doc.probability == 100` value change
- Recipient: configurable (likely the Sales Person + Quote Owner)
- Channel: System + Email

Or — better — use programmatic `frappe.sendmail()` from a `before_save` hook to keep the recipient list dynamic via Avientek Settings.

---

## Implementation phases

### Phase 0 — Remove QAR (per your decision tonight)

| Item | Action |
|---|---|
| `Quotation Action Request` doctype | Delete via patch (file: `avientek/patches/remove_quotation_action_request.py`) — drops table + DocType record |
| `Quotation Action Request Approval` workflow | Delete via patch — drops Workflow + Workflow Transition + Workflow State references |
| `seed_quotation_action_request_workflow` patch | Remove from `patches.txt` + `migrate.py`, delete the file |
| `avientek_quotation_restricted_role` child doctype | KEEP — still used by Restricted Roles RBAC (independent of QAR) |
| `quotation_high_probability.py` validators | KEEP — still enforce the field lock; will simplify by replacing the QAR-redirect throw with a "use Document Approval section" message |
| Quotation JS "Action Request" custom button | Remove (replace with the Document Approval section UX, like SO has) |
| `smoke_quotation_action_request.py` | Delete |
| `smoke_quotation_high_prob.py` | Update — remove QAR refs, keep field-lock + RBAC + inline-bump checks |
| `docs/qa/quotation_high_probability_test_cases.md` | Update Section 5 (QAR flow) → replace with Document Approval flow |
| Workflow Action Master records: `Approve L1`, `Approve L2` (created by QAR seeder) | Drop if not used elsewhere |

The existing `cleanup_high_prob_residue.py` script from 2026-05-06 was built for exactly this scenario (cross-branch artifact removal). Reuse the pattern.

### Phase 1 — Add custom fields to Quotation

- Add 5 custom fields to `avientek/fixtures/custom_field.json`
- Add `quote_approval_role` field to Avientek Settings
- Smoke: assert all 5 fields exist + correct mandatory_depends_on

### Phase 2 — Extend Quotation workflow

- Modify the active V2 workflow OR create a new `Quotation Approval Workflow Avientek (V3)` and switch the active flag (matches the SO `Sales Order Updated` rename pattern)
- Add the 6 new states + ~10 new transitions
- Idempotent seeder patch (similar pattern to QAR seeder, but on Quotation)
- Smoke: assert all states + transitions present, conditions correct

### Phase 3 — Server-side validator update

- Modify `enforce_high_prob_lock_on_save` in `quotation_high_probability.py`:
  - Allow saves when workflow_state is `Approved for Update` or `Sent for Revision`
  - Allow saves when only `Quotation Item.custom_special_price*` fields changed
  - Replace QAR-redirect throw with "Tick Request for Update / Cancellation Check + add note + Save"
- Smoke: assert each scenario allowed/blocked correctly

### Phase 4 — Special Prices carve-out

- Add Property Setters to flag the 4 special-price fields as `allow_on_submit=1` on Quotation Item
- Update validator to detect "only special-price changed" path
- Smoke: assert special_price editable on locked quote without workflow trigger

### Phase 5 — Probability 100 notification

- Add `Notification` record OR programmatic `frappe.sendmail()` hook
- Define recipient list (TBD with Sridhar/Rahul)
- Smoke: assert notification fires on prob → 100 transition

### Phase 6 — Update QA test doc

- Replace `docs/qa/quotation_high_probability_test_cases.md` Section 5 (QAR flow) with new Document Approval flow
- Add Section 6: Special Prices carve-out
- Add Section 7: Probability 100 notification

### Phase 7 — End-to-end test on test server (qcs-avntk-test)

- Pick a sample submitted quote (1,704 high-prob quotes available)
- Walk through: Tick Request for Update → fill note → Save → Approver approves → user edits → Sends for Approval → Approver approves → quote back to Approved
- Same for Cancellation flow
- Same for inline 75 → 100 bump
- Same for special_price update
- Same for prob → 100 notification

---

## What stays / what goes — summary

| Component | Status | Reason |
|---|---|---|
| QAR doctype | **REMOVE** | Replaced by Document Approval section on Quotation itself |
| QAR workflow | **REMOVE** | Replaced by extended Quotation V2 workflow |
| QAR seeder patch | **REMOVE** | Workflow lives on Quotation now |
| QAR JS button on Quotation | **REMOVE** | Replaced by Document Approval section UX |
| `Avientek Quotation Restricted Role` child doctype | **KEEP** | Still drives RBAC (Approved + 100 visibility) — independent of QAR |
| `Avientek Settings → Quotation High-Probability Workflow` section | **MODIFY** | Drop `quote_high_prob_l1_role`, `quote_high_prob_l2_role`. Add `quote_approval_role` (single approver). Keep `quote_high_prob_creator_role` + `quote_high_prob_restricted_roles`. |
| `quotation_high_probability.py` validators | **KEEP + MODIFY** | Lock logic stays. Throw messages updated. |
| `c60bc55` inline 75→100 bump | **KEEP** | Independent of QAR; still required |
| `Quotation-probability-allow_on_submit=1` Property Setter | **KEEP** | Independent of QAR |
| `smoke_quotation_action_request.py` | **DELETE** | QAR gone |
| `smoke_quotation_high_prob.py` | **MODIFY** | Update QAR-related checks to Document Approval checks |
| `Avientek Signature Image` doctype + signature_images on Avientek Settings | **KEEP** | Unrelated |

---

## Open questions for Sridhar / Rahul

1. **Approver role**: single role mirroring SO's `Supply Chain Head` pattern. Pick: `CS` / `GM-CS` / new role / configurable via Avientek Settings (recommended).

2. **Special prices fields**: confirm the exact field names allowed inline. My list: `custom_special_price`, `custom_special_rate`, `custom_special_price_note`, `custom_addl_discount_amount`. Add/remove per Rahul's exact intent.

3. **100% notification recipients**: who? Quote owner only? Sales Person? Sales Person's manager? Account manager?

4. **QAR removal urgency**: ship Phase 0 (cleanup) immediately, or include with Phases 1-7 in one batch?

5. **Workflow naming**: extend existing `Quotation Approval Workflow Avientek (V2)` in place, or create `Quotation Approval Workflow Avientek (V3)` and switch active flag (matches SO's `Sales Order Updated` rename pattern)?

6. **Sent for Revision** state on SO has a "Save" self-loop transition (Save → Sent for Revision). This lets the user edit + save without leaving the state. Mirror on Quotation? Recommended: yes.

7. **Cancellation Reason**: SO has both `custom_cancellation_check` (Check) and `custom_cancellation_reason` (Small Text). Mirror exactly — separate fields for update reason vs cancellation reason — or unify under `custom_revision_note`?

---

## Effort estimate

| Phase | LOC | Time |
|---|---|---|
| 0 — Remove QAR | ~150 LOC (patch + cleanup) | 1-2 hours |
| 1 — Custom fields | ~80 LOC fixture | 30 min |
| 2 — Workflow | ~200 LOC seeder | 2-3 hours |
| 3 — Validator update | ~30 LOC | 30 min |
| 4 — Special prices | ~50 LOC | 1 hour |
| 5 — 100% notification | ~50 LOC | 1 hour |
| 6 — Doc update | docs only | 1 hour |
| 7 — Smoke updates | ~150 LOC | 1-2 hours |
| **Total** | ~700 LOC | **8-10 hours of dev** |

Roughly a 1-day implementation + 1-day UAT cycle.
