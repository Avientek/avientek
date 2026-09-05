"""Verify warn_backdated_batch_insertion (TSK-2026-00700) against the REAL
anomaly on the restore: DN-FZCO-26-01397-1 was backdated to 08-31 11:58, before
DN-FZCO-26-01364 (08-31 14:03) consumed the same batch BN18567 @ T1-7SEAS,
which repost pushed to -1.

    bench --site avintek.local execute avientek.scripts.verify_backdated_batch_warning.run
"""
import frappe
from avientek.stock.batch_negative_guard import (
    _backdated_batch_warnings,
    _latest_later_batch_movement,
)


def run():
    # A) POSITIVE — the real backdated amendment must be flagged
    doc = frappe.get_doc("Delivery Note", "DN-FZCO-26-01397-1")
    warns = _backdated_batch_warnings(doc)
    hit = [w for w in warns if w["batch_no"] == "BN18567" and w["warehouse"] == "T1-7SEAS - A"]
    print("A) DN-FZCO-26-01397-1 warnings:", [(w["batch_no"], w["warehouse"], str(w["later_dt"])[:19], w["later_voucher"]) for w in warns])
    a_ok = bool(hit)
    print("   PASS (flags BN18567 backdated insertion):", a_ok)

    # B) core detection both directions on BN18567 @ T1-7SEAS
    later_hit = _latest_later_batch_movement("T1-7SEAS - A", "BN18567", "2026-08-31 11:58:56", exclude_voucher="DN-FZCO-26-01397-1")
    print("\nB) later movement after 2026-08-31 11:58 (excl self):", later_hit)
    b1 = later_hit is not None
    later_none = _latest_later_batch_movement("T1-7SEAS - A", "BN18567", "2099-01-01 00:00:00")
    print("   later movement after 2099 (should be None):", later_none)
    b2 = later_none is None
    print("   PASS (finds later when backdated; None when latest):", b1 and b2)

    # C) NEGATIVE — a doc posted as the LATEST movement must NOT warn
    class _Mock:
        doctype = "Delivery Note"
    m = _Mock()
    m.items = doc.items            # same batches
    m.posting_date = "2099-01-01"  # far future = latest
    m.posting_time = "00:00:00"
    m.name = "TEST-FUTURE"
    m.flags = frappe._dict()
    m.get = lambda k, d=None: getattr(m, k, d)
    neg = _backdated_batch_warnings(m)
    print("\nC) future-dated doc warnings (should be empty):", neg)
    c_ok = (neg == [])
    print("   PASS (no false positive when latest):", c_ok)

    print("\n=== RESULT:", "PASS" if (a_ok and b1 and b2 and c_ok) else "FAIL", "===")
