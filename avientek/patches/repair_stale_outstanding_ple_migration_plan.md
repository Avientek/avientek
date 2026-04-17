# KSA PLE Doubling Repair — Production Migration Plan

**Site:** `avientekv21.frappe.cloud`
**Company targeted:** `AVIENTEK TRADING LLC`
**Patch commit:** `ad3415f` on `upstream/master`
**Prepared:** 2026-04-17

---

## 1. Background

A past GL rebuild (commit `5f0ac6f`) cleaned up `tabGL Entry` for AVIENTEK TRADING LLC but did **not** clean `tabPayment Ledger Entry`. PLE retained duplicate rows per voucher. ERPNext computes `Sales Invoice.outstanding_amount` (and `Purchase Invoice.outstanding_amount`) from PLE — so every affected voucher shows 2× the real balance. The customer flagged this as "AR doubled on Sky Information / CUST-2024-00436 invoices".

**Root cause verified**, not speculated:
- `tabGL Entry` is clean (1 party-account row per voucher)
- `tabPayment Ledger Entry` has 2 active rows (`delinked=0`) per voucher — same voucher/account/party/against/amount
- `outstanding_amount` on docs equals the sum of PLE (= 2×)

---

## 2. Pre-Migration Production Baseline

Captured from production via API, 2026-04-17 before migration:

### Sales Invoice (AR)
| Metric | Value |
|---|---|
| Submitted SIs | 1,392 |
| SIs with `outstanding_amount > 0` | 167 |
| SIs doubled (`OS == 2 × base_grand_total`) | **154** |
| Total AR balance (current, inflated) | SAR 11,719,817.03 |
| Overstatement (SAR) | ~ SAR 3,452,420 |
| Projected AR after fix | ~ SAR 8,267,397 |

### Purchase Invoice (AP)
| Metric | Value |
|---|---|
| Submitted PIs | 558 |
| PIs with `outstanding_amount > 0` | 451 |
| PIs doubled (`OS == 2 × base_grand_total`) | **440** |
| Total AP balance (current, inflated) | SAR 66,157,089.09 |
| Overstatement (SAR) | SAR 30,986,912.11 |
| Projected AP after fix | ~ SAR 35,170,177 |

### Customer CUST-2024-00436 (the WhatsApp case)
| Metric | Value |
|---|---|
| Submitted SIs for this customer | 20 |
| Current total outstanding | SAR 125,700.08 |
| Expected after fix | ~ SAR 75,960 (excluding fully-paid and credit-noted) |

### Four disputed invoices (from WhatsApp screenshot)
| Invoice | grand_total | Current OS (inflated) | Ratio |
|---|---|---|---|
| INV-AT-25-00921-1 | 26,220.00 | 26,220.00 | 1.00 (already correct — had a payment) |
| INV-AT-25-00933 | 20,569.89 | 41,139.78 | **2.00** |
| INV-AT-25-00976-1 | 27,179.64 | 54,359.28 | **2.00** |
| INV-AT-26-00124 | 1,990.51 | 3,981.02 | **2.00** |

### Local verification (performed on local clone of prod)
| Metric | Local before fix | Local after fix |
|---|---|---|
| Duplicate PLE groups | 3,479 | **0** |
| PLE rows delinked | — | 3,504 |
| Vouchers touched | — | 2,592 |
| Invoices outstanding refreshed | — | 1,354 |
| SI `outstanding_amount` mismatches vs PLE balance | many | **0** |
| PI `outstanding_amount` mismatches vs PLE balance | many | **0** |
| Errors during run | — | **0** |

**By voucher type cleaned on local:**
- Payment Entry: 1,395 duplicate groups
- Sales Invoice: 1,222 duplicate groups
- Journal Entry: 758 duplicate groups
- Purchase Invoice: 104 duplicate groups

---

## 3. Migration Steps (Production)

### Step 1 — Deploy the patch
On Frappe Cloud dashboard:
1. **Update and Migrate** to pull commit `ad3415f`.
2. Confirm `/assets/avientek/` rebuilt and app imports succeed.

### Step 2 — Dry-run on production
In Frappe Cloud bench console for `avientekv21.frappe.cloud`:
```python
from avientek.patches.repair_stale_outstanding_ple import purge_duplicate_ple
result = purge_duplicate_ple(dry_run=1, company="AVIENTEK TRADING LLC")
print(result)
```

**Expected shape (must match within ±5% before proceeding):**
- `scanned_groups`: ~3,400–3,600
- `ple_delinked`: ~3,400–3,600
- `vouchers_affected`: ~2,500–2,700
- `outstanding_updated`: 0 (dry-run does no writes)
- `errors`: 0
- `by_voucher_type`: Payment Entry ≈ 1,395, Sales Invoice ≈ 1,222, Journal Entry ≈ 758, Purchase Invoice ≈ 104

**If numbers deviate significantly — stop and send me the output before running with `dry_run=0`.**

### Step 3 — Apply the fix
```python
import datetime
run_start = datetime.datetime.now().isoformat()
print("STARTED:", run_start)
result = purge_duplicate_ple(dry_run=0, company="AVIENTEK TRADING LLC")
print(result)
```

**Record `run_start` timestamp — needed for rollback.**

### Step 4 — Post-fix refresh of cross-referenced invoices
(Covers the 28 edge cases where JE/PE dedup reduces an invoice's balance.)
```python
import frappe
from frappe.utils import flt
from avientek.patches.repair_stale_outstanding_ple import _compute_outstanding

updated = 0
for dt, party_field, account_field, party_type in [
    ("Sales Invoice", "customer", "debit_to", "Customer"),
    ("Purchase Invoice", "supplier", "credit_to", "Supplier"),
]:
    rows = frappe.db.sql(
        f"SELECT name, {party_field} AS party, {account_field} AS account, "
        f"outstanding_amount FROM `tab{dt}` "
        f"WHERE company='AVIENTEK TRADING LLC' AND docstatus=1",
        as_dict=True,
    )
    for inv in rows:
        new_os = _compute_outstanding(dt, inv.name, inv.account, party_type, inv.party)
        prec = frappe.get_precision(dt, "outstanding_amount") or 2
        new_os = flt(new_os, prec)
        if abs(flt(inv.outstanding_amount, prec) - new_os) > 0.01:
            frappe.db.set_value(dt, inv.name, "outstanding_amount", new_os, update_modified=False)
            updated += 1
frappe.db.commit()
print(f"Refreshed outstanding on {updated} invoices")
```

Expected `updated`: ~20–40.

---

## 4. Post-Migration Verification

Run these checks after Step 4. **All must pass** before declaring success.

### 4.1 Zero duplicate PLE groups remaining
```sql
SELECT COUNT(*) AS duplicate_groups FROM (
  SELECT 1 FROM `tabPayment Ledger Entry`
  WHERE delinked=0 AND company='AVIENTEK TRADING LLC'
  GROUP BY voucher_type, voucher_no, account, party_type, party,
           against_voucher_no, amount_in_account_currency
  HAVING COUNT(*) > 1
) g;
```
**Pass:** `duplicate_groups = 0`.

### 4.2 SI outstanding == PLE balance
```sql
SELECT COUNT(*) AS si_mismatches FROM (
  SELECT si.name, si.outstanding_amount AS os,
         (SELECT COALESCE(SUM(amount_in_account_currency),0) FROM `tabPayment Ledger Entry`
          WHERE against_voucher_no=si.name AND delinked=0 AND account=si.debit_to
            AND party=si.customer AND party_type='Customer') AS ple_bal
  FROM `tabSales Invoice` si
  WHERE si.company='AVIENTEK TRADING LLC' AND si.docstatus=1
) t WHERE ABS(os - ple_bal) > 1;
```
**Pass:** `si_mismatches = 0`.

### 4.3 PI outstanding == PLE balance
```sql
SELECT COUNT(*) AS pi_mismatches FROM (
  SELECT pi.name, pi.outstanding_amount AS os,
         (SELECT COALESCE(SUM(amount_in_account_currency),0) FROM `tabPayment Ledger Entry`
          WHERE against_voucher_no=pi.name AND delinked=0 AND account=pi.credit_to
            AND party=pi.supplier AND party_type='Supplier') AS ple_bal
  FROM `tabPurchase Invoice` pi
  WHERE pi.company='AVIENTEK TRADING LLC' AND pi.docstatus=1
) t WHERE ABS(os - ple_bal) > 1;
```
**Pass:** `pi_mismatches = 0`.

### 4.4 WhatsApp 4 invoices — spot check
```sql
SELECT name, grand_total, outstanding_amount,
       ROUND(outstanding_amount/grand_total, 2) AS ratio, status
FROM `tabSales Invoice`
WHERE name IN ('INV-AT-25-00933','INV-AT-25-00921-1',
               'INV-AT-25-00976-1','INV-AT-26-00124');
```
**Pass:** all four show `ratio = 1.00`.

### 4.5 Total AR reconciliation
```sql
SELECT ROUND(SUM(outstanding_amount),2) AS total_ar
FROM `tabSales Invoice`
WHERE company='AVIENTEK TRADING LLC' AND docstatus=1;
```
**Pass:** value is reduced from pre-migration 11,719,817.03 by ≈ 3.4M (expected ≈ 8,267,000 ± 100k).

### 4.6 Total AP reconciliation
```sql
SELECT ROUND(SUM(outstanding_amount),2) AS total_ap
FROM `tabPurchase Invoice`
WHERE company='AVIENTEK TRADING LLC' AND docstatus=1;
```
**Pass:** value is reduced from pre-migration 66,157,089.09 by ≈ 31M (expected ≈ 35,170,000 ± 500k).

### 4.7 Status coherence
```sql
-- Should return 0 rows — no "Paid" invoice with outstanding > 0.01
SELECT COUNT(*) AS bad_paid_status FROM `tabSales Invoice`
WHERE company='AVIENTEK TRADING LLC' AND docstatus=1
  AND outstanding_amount > 0.01 AND status = 'Paid';

-- Should return 0 rows — no zero-outstanding invoice still marked Overdue/Unpaid
SELECT COUNT(*) AS stale_overdue FROM `tabSales Invoice`
WHERE company='AVIENTEK TRADING LLC' AND docstatus=1
  AND outstanding_amount = 0
  AND status NOT IN ('Paid','Credit Note Issued','Return','Closed');
```
**Pass:** both return 0.

### 4.8 Customer CUST-2024-00436 (the WhatsApp customer)
```sql
SELECT ROUND(SUM(outstanding_amount),2) AS total_os
FROM `tabSales Invoice`
WHERE customer='CUST-2024-00436' AND company='AVIENTEK TRADING LLC'
  AND docstatus=1;
```
**Pass:** value drops from pre-migration 125,700.08 to ~75,960 (about half).

### 4.9 Accounts Receivable report in the UI
Open `https://avientekv21.frappe.cloud/app/query-report/Accounts Receivable` with filter `Company = AVIENTEK TRADING LLC`. Spot-check:
- Customer CUST-2024-00436 row totals show ~SAR 75,960 (not 125K)
- INV-AT-25-00933 row: Invoiced 20,569.89, Outstanding 20,569.89 (not 41,139)
- INV-AT-25-00976-1 row: Outstanding 27,179.64 (not 54,359)

### 4.10 No new Error Log entries
```sql
SELECT COUNT(*) FROM `tabError Log`
WHERE creation >= '<run_start timestamp>';
```
**Pass:** no entries with title mentioning the patch.

---

## 5. Rollback Procedure

If any of sections 4.1–4.10 fail OR customer reports new discrepancies, immediately:

```python
from avientek.patches.repair_stale_outstanding_ple import undo_repair
result = undo_repair(
    since="<run_start timestamp from Step 3>",
    company="AVIENTEK TRADING LLC"
)
print(result)
```

This re-links every PLE row this patch delinked after `run_start` and re-derives `outstanding_amount` for affected SI/PI from the restored (original, duplicated) state.

After rollback:
- `duplicate_groups` returns to ~3,500
- Customer AR returns to doubled state
- No other side effects

---

## 6. Known Residual Issues (not addressed by this patch)

These existed before the patch and are not affected by it:

| Issue | Scope | Impact | Fix path |
|---|---|---|---|
| `paid_amount` field stale on ~1,232 SIs | pre-existing | low — only print formats or custom reports reading this field | manual Payment Reconciliation per invoice, separate ticket |
| 19 Payment Entries with PLE rows not matching GL | pre-existing | nil on AR/AP totals; visible only on Payment Reconciliation of those specific PEs | Repost Accounting Ledger per doc |
| 3 Journal Entries with PLE rows not matching GL | pre-existing | same as above | Repost Accounting Ledger per doc |
| 6 SIs with status "Partly Paid" and negative outstanding | pre-existing — overpayments | low | reconcile overpayments to advance account |

---

## 7. Sign-Off Checklist

- [ ] Patch commit `ad3415f` pulled via Update and Migrate
- [ ] Dry-run output matches Section 3 expected shape
- [ ] Real run completed with `errors = 0`
- [ ] Step 4 follow-up refresh completed
- [ ] Section 4.1–4.10 all pass
- [ ] Customer CUST-2024-00436 informed that AR now matches ledger
- [ ] WhatsApp thread closed with before/after screenshots
- [ ] `run_start` timestamp saved (needed for rollback window — keep 7 days)

---

## 8. What Was Explicitly NOT Done

Documented here so reviewers know the boundary:

- **No change to GL Entry** — ledger was already correct before the patch.
- **No change to Payment Entry / Journal Entry documents** — only their PLE rows.
- **No change to `paid_amount` on any invoice** — stale values remain stale (pre-existing).
- **No automatic auto-run on migrate** — patch is deliberately NOT in `patches.txt`. Must be invoked explicitly.
- **No cross-company run** — `execute()` defaults hard-code `AVIENTEK TRADING LLC` and `run_repair` / `purge_duplicate_ple` require the `company` kwarg to be set when called in practice.
- **No modification of historical reports** — previously-exported CSVs / PDFs remain with old doubled numbers. Re-export if needed.
