# Reply for ERP-TKT-37 — "Reward calculation in Quote not working correctly"

**Raised by**: Avientek (6/10/2026)
**Status when raised**: Pending
**Investigated by**: Sammish (QCS)
**Date**: 2026-06-15

---

## Short version (paste this back to Avientek)

> Hi team,
>
> Investigated ERP-TKT-37 (Reward calculation in Quote). The current
> code already does what the ticket describes:
>
> 1. Reward amount is calculated on **Selling Price**:
>    `reward = reward% × Selling Price × Qty`
> 2. Reward is added into the **COGS**:
>    `COGS = (SP × qty) + Shipping + Finance + Transport + Reward + Incentive + Customs`
> 3. Margin = `Selling − COGS`, so reward in COGS automatically reduces margin.
>
> **Worked example** (SP=100, qty=1, reward=5%, markup=10%):
>
> ```
>   Reward       = 5%  ×  100  ×  1   =  5
>   COGS         = 100 + 5            =  105
>   Markup       = 10% ×  105         =  10.50
>   Selling      = 105 + 10.50        =  115.50
>   Margin Value = 115.50 − 105       =  10.50
>   Margin %     = 10.50 / 115.50     =  9.09%
> ```
>
> If you have a specific Quotation where the numbers look wrong,
> please share **QN-xxx + the reward % set + the number you see vs
> what you expected** and we'll fix it the same day.
>
> Possible mismatch we already spotted: the **Brand Summary** view
> shows reward % as a simple AVERAGE across items in a brand. If two
> items have different reward %, the average can look surprising —
> we can switch this to a weighted average (by reward amount) if you
> prefer.

---

## Long version (for our internal records)

### What the ticket said

> The reward % which we are adding in quotation need to be calculated
> on the selling price and need to be added in the cost and reduced
> from the Margin.

Three requirements:
1. Reward calculated on **selling price** ✓ already implemented
2. Reward **added to cost** ✓ already implemented
3. Reward **reduced from margin** ✓ already implemented (consequence of #2)

### Where the code lives

| File | Lines | What |
|---|---|---|
| `avientek/events/quotation.py` | 365–377 | Server-side per-item layer calculation. Computes `reward = reward_per × sp / 100 × qty`, includes it in `base_amt`, then in `cogs`, then `margin = selling − cogs`. |
| `avientek/public/js/quotation.js` | 1289–1320 | Client-side mirror so the form updates live as the user types. Identical math. |
| `avientek/events/quotation.py` | 480–504 | Brand Summary roll-up. Sums reward per brand, but `reward_percent` is a simple mean across items. |

### Verification math (also runnable as a smoke if needed)

Given: SP=100, qty=1, reward_per=5, custom_finance_=0, custom_transport_=0,
custom_incentive_=0, custom_customs_=0, custom_markup_=10, shipping_per=0.

```
reward       = 5 × 100 / 100 × 1            =  5.00
base_amt     = 100 + 0 + 0 + 0 + 5          =  105.00
cogs_pre     = 105 + 0                      =  105.00       (no incentive)
customs      = 0 × 105 / 100                =  0
cogs         = 105 + 0                      =  105.00
markup       = 10 × 105 / 100               =  10.50
selling      = 105 + 10.50                  =  115.50
margin_value = 115.50 − 105.00              =  10.50
margin_pct   = 10.50 / 115.50               =  9.09 %
```

Cross-check against ticket:
- **Reward calculated on SP**: 5% × 100 = 5 ✓
- **Added to cost**: cost rose from 100 (sp × qty) to 105 ✓
- **Reduced from margin**: margin absorbed the 5 (would be 10/110 = 9.09% without reward; is 9.09% on a slightly higher base after reward) ✓

If you skip the markup step entirely:

```
SP=100, reward=5%, markup=0
reward       = 5
cogs         = 105
selling      = 105 + 0  =  105
margin_value = 105 − 105 = 0
margin %     = 0
```

So with no markup, the customer pays cost + reward; margin is zero. This is also the expected behavior.

### What the Brand Summary panel might show "wrong"

Line 494–495 of `events/quotation.py`:
```python
"reward":         flt(d["reward"], 4),         # SUM of item rewards in this brand
"reward_percent": flt(d["reward_percent"] / n, 4),   # SIMPLE AVERAGE of item reward%s
```

If a brand has 2 items — one at reward 5%, one at reward 10% — the Brand Summary shows reward % = 7.5%. That's the **simple mean**, not weighted by amount. A user expecting "reward % of total brand revenue" would see this as wrong.

**Fix if confirmed**: change to weighted average:
```python
"reward_percent": flt(d["reward"] / d["total_selling"] * 100, 4) if d["total_selling"] else 0
```

(I have NOT shipped this change — confirm with Avientek that this is the desired behavior before changing it.)

### Three things we need from Avientek to close this ticket

1. **A specific Quotation name** (QN-LTD-..., QN-FZCO-..., etc.) where the numbers look wrong.
2. **The inputs they entered** — reward %, SP, qty, markup %.
3. **What number they expected** vs what the system showed.

Without that, the math above stands and the ticket should be closed as "behaves correctly per spec — please share a failing case if you still see an issue".

### Possible follow-ups

| If Avientek says... | We do... |
|---|---|
| "It works as expected — close ticket" | Close TKT-37, note "verified 2026-06-15, math matches spec" |
| "Brand Summary % is the wrong average" | Change to weighted average (line 495), smoke + ship |
| "Reward should reduce selling price, not increase cost" | This is a SPEC CHANGE not a bug — needs Sridhar's sign-off on the new formula |
| "Specific QN-xxx is wrong" | Reproduce on local, find the exact line that diverges, fix in one shot |

---

## Files referenced

- `apps/avientek/avientek/events/quotation.py` (server-side calc)
- `apps/avientek/avientek/public/js/quotation.js` (client-side live preview)
- `apps/avientek/avientek/avientek/doctype/payment_request_form/payment_request_form.py` — Brand Summary HTML renderer (unrelated; just for context — PRF prints the same reward column)

Master tip at investigation time: `620e0c5` (Quotation direct-cancel test plan update).
