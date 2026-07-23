# Stock valuation bug — batches getting priced at zero on delivery

**Raised by**: client, via two downloaded reports (Stock Ledger + Stock Balance
for Item I024926, Stores - KSA) showing an absurd Valuation Rate of
₹5,805.90/pc for an item that only ever cost ~₹242/pc.
**Investigated by**: Sridhar, 2026-07-23
**Status**: root cause of the *symptom* confirmed with data; exact trigger
inside ERPNext core not yet pinned; scope is systemic, not a one-off. A
safety-net code fix has been written — an earlier version of it patched the
wrong method (see "Safety-net fix" below for the correction) — awaiting
verification against real MAT-STE-00774 data and Sammish's review before
going to production.

**Second occurrence same day**: Jithin reported Item **I030969** on Repack
Stock Entry **MAT-STE-00774** (already amendment #7 — same symptom
reproduced on every retry) going to a **source row**, not a Delivery Note.
Confirms the .md's existing note that this isn't DN-only (MAT-STE-00513 was
already flagged in the system-wide scan). This occurrence hits the
*non-batchwise-valuation* path inside `BatchNoValuation`
(`DeprecatedBatchNoValuation.calculate_avg_rate_for_non_batchwise_valuation`),
a different internal path than the I024926 trace below (which went through
`get_batch_no_ledgers`, the batchwise-valuation path) — so this looks like
the same *symptom* surfacing from more than one internal cause, which is
exactly why the fix below is a safety net rather than a targeted patch to
one query.

---

## Short version (for Sammish)

We found a real, ongoing bug in ERPNext's stock valuation engine — not
something specific to our customizations, and not a data-entry mistake.

**What happens**: when a Delivery Note (or Stock Entry) consumes a batch of
stock that was received only a few minutes earlier, ERPNext sometimes
records that batch as costing **₹0** instead of its real cost. The missing
cost doesn't disappear — it gets dumped onto whatever stock is left behind,
which is why some items show wildly inflated valuation rates.

**Scale** (found by scanning the whole stock ledger, read-only, nothing
changed):
- **716 confirmed-wrong line entries**
- **311 distinct vouchers** (mostly Delivery Notes, at least one Stock Entry)
- **409 distinct items**, **20 warehouses**
- Date range **2025-01-17 → 2026-07-06** — 18 months, still happening 2 weeks
  ago at the time of writing.
- Concentrated on large multi-batch delivery notes (e.g. DN-LLC-26-00803: 41
  wrong rows in one document), consistent with a timing/race condition that
  gets more likely under load rather than a rare fluke.

**What we ruled out** (so nobody re-investigates these):
- Not a rounding/display issue — the underlying `Serial and Batch Entry.
  incoming_rate` is persisted as literally `0`.
- Not the classic "batch double-counting" bug we already patched in
  `avientek/__init__.py` / `avientek/patches/` (those patches only affect
  items with `batch_no` set directly on the Stock Ledger Entry; this bug
  hits items using the modern Serial and Batch Bundle path).
- Not GRN/DN submitted out of order — checked actual `creation`/`modified`
  timestamps for the original case; the goods receipt really was submitted
  and committed ~3 minutes before the delivery note.
- Not a bug in the valuation *math* — re-running ERPNext's own
  `BatchNoValuation` class right now, on the same historical data, computes
  the correct rate. The logic is sound; something transient at the moment of
  submission produced and persisted a wrong number.
- Checked one specific upstream ERPNext bug that looked like an exact match
  ([PR #51729](https://github.com/frappe/erpnext/pull/51729) — "FIFO items
  with Use Batchwise Valuation disabled getting incoming_rate=0") — our
  installed version (v15.111.0) already contains that fix
  (`serial_and_batch_bundle.py:764-807`), so it isn't this.

**What's NOT done yet**: the exact trigger (which of ERPNext's internal
valuation queries misses the just-received batch, and why) hasn't been
caught in the act — that needs either a live reproduction under the same
conditions (large multi-batch DN, batch received minutes prior) or deeper
tracing than static code reading can give.

**Decision needed from Sammish**:
1. How urgent is a code-level fix (or whether to raise it upstream with
   ERPNext, since our version may not be uniquely affected)?
2. What to do about the 716 already-wrong historical entries — this is a
   financial correction (touches submitted stock value / potentially GL),
   so per usual it shouldn't be run without Sammish's sign-off. The
   standard ERPNext tool for this is `Repost Item Valuation` per affected
   item+warehouse, but at this scale it's worth deciding whether to do it
   in bulk or case-by-case as clients notice.

---

## Long version (internal record)

### The original symptom

Item **I024926** (C6R Ceiling Speakers Black), warehouse **Stores - KSA**,
company **AVIENTEK TRADING LLC**. Full Stock Ledger for this item:

| Date | Voucher | Qty | Rate | Balance Qty | Balance Value |
|---|---|---|---|---|---|
| 2026-06-16 | GRN-KSA-26-00115 | +2 | 242.28 | 2 | 484.56 |
| 2026-06-30 19:18:20 | GRN-KSA-26-00129 | +48 | 241.91 | 50 | 12,096.36 |
| 2026-06-30 19:20:19 | DN-AT-26-00397 | −48 | **10.10** | 2 | 11,611.80 |

The delivery note should have removed ~₹11,612 in value (48 units at the
~241.93 average cost on the books two minutes earlier). Instead it only
removed ₹484.56, leaving the 2 remaining units carrying almost all the true
cost of the 48 that left — hence the ₹5,805.90/pc valuation rate the client
saw on the Stock Balance report.

### Batch-level trace

The DN's outward Serial and Batch Bundle (`854c356e84e98ffc728c`) has two
entries:

| Batch | Qty | Persisted incoming_rate |
|---|---|---|
| BN01875 | −2 | 241.915 ✓ correct |
| BN17455 | −46 | **0.0** ✗ wrong |

BN17455 was the batch created moments earlier by GRN-KSA-26-00129
(19:18:20), consumed by the DN at 19:20:19 — under 2 minutes later.

Re-running ERPNext's own `BatchNoValuation` class against the exact same
SLE context, right now, computes:
```
batch_avg_rate = {'BN01875': 241.915, 'BN17455': 241.9125}
```
Both correct — including BN17455, which was persisted as 0 at submit time.
This is why we believe the calculation logic itself is not at fault; it's a
timing-sensitive issue in what data was visible/committed at the exact
moment the DN's rate was computed and saved.

### Scope scan (system-wide)

Ran a read-only scan for the same signature everywhere: an outward
`Serial and Batch Entry` with `incoming_rate = 0` (or NULL) for a batch that
demonstrably has real positive receipt value elsewhere in the ledger.

Result: 716 confirmed rows / 311 vouchers / 409 items / 20 warehouses,
2025-01-17 through 2026-07-06. Not exclusively Delivery Notes — one Stock
Entry (`MAT-STE-00513`) shows the same symptom.

### Artifacts (all read-only, no data touched)

| File | Purpose |
|---|---|
| `avientek/scripts/diag_stock_valuation_i024926.py` | `run()` — dumps raw SLEs + SBB/SBE rows for I024926 @ Stores - KSA. `run_batch_valuation_trace()` — re-runs ERPNext's live `BatchNoValuation` against the DN's bundle to prove the math is correct on replay. |
| `avientek/scripts/diag_zero_rate_outward_batches.py` | System-wide scan for the same signature. Writes a CSV to `sites/<site>/private/files/zero_rate_outward_batches_<timestamp>.csv` with every affected voucher/item/batch and the expected-vs-persisted rate. |

Both can be re-run any time via `bench --site avientek.localhost execute
avientek.scripts.<module>.<function>` — neither writes to Stock Ledger
Entry, Serial and Batch Bundle, or any submitted document.

### Leads checked and ruled out

- `avientek/__init__.py` batch-valuation patches (double-counting fixes,
  2026-06) — those target legacy `Stock Ledger Entry.batch_no`-only
  transactions with no `serial_and_batch_bundle`; this bug hits SBB-based
  transactions, a different code path.
- [ERPNext PR #51729](https://github.com/frappe/erpnext/pull/51729) /
  [#51752](https://github.com/frappe/erpnext/pull/51752) — "FIFO items
  posting to a batch with Use Batchwise Valuation disabled get
  incoming_rate=0 due to stock queue not updating." Very similar symptom,
  but our installed `serial_and_batch_bundle.py` (v15.111.0) already has
  this exact fix in `set_incoming_rate_for_inward_transaction`
  (lines 764-807) — confirmed by reading the file directly, not just the
  changelog. So this is a different bug than the one already fixed
  upstream.

### Safety-net fix (2026-07-23, corrected same day, pending Sammish review)

**First attempt (wrong, superseded)**: wrapped `BatchNoValuation.
get_incoming_rate()`. On review this method turned out to NOT be in either
real call path that persists a batch's rate — both
`SerialAndBatchBundle.set_incoming_rate_for_outward_transaction` and
`stock_ledger.get_incoming_rate_for_serial_and_batch` read
`self.batch_avg_rate.get(batch_no)` directly and never call
`get_incoming_rate()`. Its accompanying test also only ever called
`get_incoming_rate()` directly, so it "passed" without proving the fix
would have prevented DN-AT-26-00397 or MAT-STE-00774. Caught before
this went anywhere near Sammish or production.

**Corrected fix**: `avientek/__init__.py::_patch_batch_valuation_zero_rate_safety_net`
now wraps `BatchNoValuation.calculate_avg_rate` — the method that actually
populates `self.batch_avg_rate`, the dict both real callers read from. The
shared guard logic lives in `avientek._batch_valuation_zero_rate_guard` so
the test can exercise the identical code. After the original calculation
runs: for an OUTWARD transaction that isn't intentionally zero-cost
(`allow_zero_valuation_rate` on the voucher item row), for each batch whose
own qty in this transaction is negative and whose `batch_avg_rate` resolved
to a false 0, if the item+warehouse demonstrably holds real value right now
(`Bin.valuation_rate > 0`), override that batch's rate with the Bin
valuation rate AND correct `self.stock_value_change` by the same delta (so
the running warehouse balance for the *next* ledger entry doesn't inherit
the error either — this is what caused the leftover 2 units to absorb the
missing cost in the I024926 case). Logs an Error Log entry every time it
fires. Genuinely zero-cost batches and inward transactions are left
untouched.

This still does **not** fix the underlying query bug(s) — we still don't
have the exact trigger pinned. It's deliberately a last-line-of-defence,
same philosophy as `avientek.stock.batch_negative_guard`: stop the wrong
number from reaching the ledger/GL, regardless of which internal path
produced it.

Rewritten test (`avientek/scripts/test_batch_valuation_zero_rate_guard.py`,
read-only, no real documents touched) now calls
`avientek._batch_valuation_zero_rate_guard` directly against synthetic
post-`calculate_avg_rate` state (the same `batch_avg_rate` /
`stock_value_change` / `batch_nos` shape the real method leaves behind):
- false-zero-with-real-value → overridden, AND `stock_value_change`
  corrected by the matching delta
- normal nonzero computed rate → passed through untouched, unchanged
  `stock_value_change`
- inward transaction (positive qty) → left untouched
- genuine `allow_zero_valuation_rate` row → left at 0 (skipped locally if
  no such row exists in this DB to look up)

**Still needs** (unchanged from before): run the rewritten test locally to
confirm it passes here too, then verification against the actual
MAT-STE-00774 / I030969 production data (this dev site's DB snapshot
predates 2026-07-23, so the real document couldn't be reproduced locally)
before this goes anywhere near production. No historical data has been
touched by this change; it only affects rate computation on *future*
submits going forward.

### Suggested next steps (for whoever picks this up)

1. Try to reproduce live: script a Purchase Receipt for a batch immediately
   followed by a Delivery Note consuming most of it, submitted within
   seconds, ideally via two concurrent background jobs/workers (the
   production pattern looks like bulk/rapid entry, possibly through
   automation or fast manual entry). If it reproduces locally, we can trace
   it with breakpoints instead of guessing from source.
2. If it reproduces, the fix is almost certainly inside
   `erpnext/stock/doctype/serial_and_batch_bundle/serial_and_batch_bundle.py`
   (`BatchNoValuation.calculate_avg_rate` / `get_batch_no_ledgers` /
   `set_incoming_rate_for_outward_transaction`) or the underlying DB
   transaction isolation around it — same family as the patches already in
   `avientek/__init__.py`, so the fix pattern (monkey-patch at app load) is
   established.
3. If it doesn't reproduce easily, worth checking whether this is already
   reported upstream under a different description, or filing a new
   ERPNext GitHub issue with our CSV as evidence — this doesn't look
   specific to Avientek's setup.
4. Historical correction (716 rows) is a separate decision from the code
   fix — do not run `Repost Item Valuation` on any of these without
   Sammish's review, since it adjusts submitted stock value / potentially
   GL entries.
