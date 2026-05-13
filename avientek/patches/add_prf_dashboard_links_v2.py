"""Re-run add_prf_dashboard_links so the new `document_reference`
DocType Link rows get added on PO / SO / SI / PI / JV / PE / DN.

Sammish 2026-05-16 (Jithin #8): the original patch (Patch Log already
recorded) only added a link via `reference_name`. For Purchase Invoice
and Debit Note rows, reference_name stores the supplier's free-text
bill_no (e.g. "#032079"), so Connections couldn't surface PRFs from
PI list views. The upgraded module now adds BOTH reference_name AND
document_reference link rows, idempotently.

This stub triggers re-execution under a new patch name. The underlying
logic is unchanged — see add_prf_dashboard_links.execute() for the
heavy lifting.
"""
from avientek.patches.add_prf_dashboard_links import execute as _execute


def execute():
	_execute()
