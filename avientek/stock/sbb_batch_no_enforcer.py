"""Forward-enforcement hook: SLE.batch_no must be NULL when SBB is attached.

Sridhar 2026-06-03 — paired with Patch A5 (one-time data cleanup) to give
a complete dynamic fix for the ERPNext v15 SBB double-count bug.

The bug: ERPNext v15 stores batch info redundantly when an SLE has a
Serial and Batch Bundle attached:
  - tabSerial and Batch Entry.qty (the canonical modern v15 location)
  - tabStock Ledger Entry.batch_no (a legacy column that ERPNext also
    auto-populates from the SBB on save in some flows)

Many ERPNext functions sum both sources without de-duplicating, causing
the same transaction to be counted twice. We've monkey-patched the three
known reader paths, but new reader paths can show up in any ERPNext
release. This hook eliminates the root data condition: whenever an SLE
with an SBB attached gets saved, its batch_no is force-NULLed BEFORE
the row hits the database.

After both Patch A5 (clean existing rows) and this hook (clean new rows)
are in place, no ERPNext reader anywhere — present or future — can
double-count, because the redundant data simply doesn't exist.

Hooked via doc_events["Stock Ledger Entry"]["before_save"].
Also runs on before_insert via the same event chain.
"""
import frappe


def enforce_sbb_null_batch_no(doc, method=None):
	"""If an SLE has a non-empty serial_and_batch_bundle, force its
	batch_no field to NULL. The SBB child rows carry the authoritative
	batch info — keeping batch_no on the SLE row is a redundant legacy
	column that causes double-counting in legacy ERPNext readers.

	Pre-v15 / direct-batch SLEs (no SBB attached) are untouched —
	their batch_no IS the authoritative value.
	"""
	sbb = getattr(doc, "serial_and_batch_bundle", None)
	if sbb and getattr(doc, "batch_no", None):
		doc.batch_no = None
