"""Patch A2 — build Negative Batch Cleanup Plan with donor pairings.

For every (item, warehouse, batch) bucket where balance < 0:
  - find a positive donor batch on the same (item, warehouse) with
    enough surplus to cover the deficit
  - if found: create/update plan row with path=REPACK, donor info, val_rate
  - if no donor: create/update plan row with path=WRITE_OFF (no donor)

Idempotent — re-run rebuilds plan rows. Existing rows that have
status=Done are LEFT ALONE (already executed). Pending / Ready / Failed
rows are refreshed with current donor data so users see live info.

Status flow:
  Pending (initial) -> Ready (Accounts/Stock Mgr ticks ready_for_execution)
  -> Done (after Patch A3 submits the Repack)
  Failed status preserved for retry diagnosis.
"""
import frappe
from frappe.utils import now_datetime


def _get_per_batch_balance(item_code, warehouse, batch_no):
	"""Single-batch balance via direct SQL — same logic as
	avientek/stock/batch_negative_guard.py (bypasses ERPNext's buggy
	get_stock_ledgers_batches)."""
	res = frappe.db.sql(
		"""
		SELECT COALESCE((
			SELECT SUM(sle.actual_qty) FROM `tabStock Ledger Entry` sle
			WHERE sle.item_code=%s AND sle.warehouse=%s AND sle.batch_no=%s
			  AND sle.is_cancelled=0
			  AND (sle.serial_and_batch_bundle IS NULL OR sle.serial_and_batch_bundle='')
		), 0) +
		COALESCE((
			SELECT SUM(sbe.qty) FROM `tabSerial and Batch Entry` sbe
			INNER JOIN `tabStock Ledger Entry` sle ON sle.serial_and_batch_bundle = sbe.parent
			WHERE sle.item_code=%s AND sle.warehouse=%s AND sbe.batch_no=%s
			  AND sle.is_cancelled=0
		), 0) AS balance
		""",
		(item_code, warehouse, batch_no, item_code, warehouse, batch_no),
	)
	return float(res[0][0]) if res and res[0] else 0.0


def _get_donor_val_rate(item_code, warehouse, batch_no):
	"""Last positive SLE's valuation_rate for this batch — used as the
	donor's per-unit value when computing estimated cleanup value."""
	res = frappe.db.sql(
		"""
		SELECT valuation_rate FROM `tabStock Ledger Entry`
		WHERE item_code=%s AND warehouse=%s AND batch_no=%s AND is_cancelled=0
		ORDER BY posting_date DESC, posting_time DESC, creation DESC
		LIMIT 1
		""",
		(item_code, warehouse, batch_no),
	)
	return float(res[0][0]) if res and res[0] else 0.0


def execute():
	wh_to_co = {
		w["name"]: w["company"]
		for w in frappe.get_all("Warehouse", fields=["name", "company"])
	}
	now = now_datetime()

	# TRUE per-batch balance — combines legacy SLE.batch_no AND SBE.qty
	# without double-counting. Mirrors the audit + the negative-batch
	# guard's _get_current_batch_balance logic.
	negatives = frappe.db.sql(
		"""
		SELECT x.item_code, x.warehouse, x.batch_no,
		       SUM(x.qty)        AS balance,
		       SUM(x.value_diff) AS value_diff
		FROM (
			SELECT sle.item_code, sle.warehouse, sle.batch_no,
			       sle.actual_qty AS qty,
			       sle.stock_value_difference AS value_diff
			FROM `tabStock Ledger Entry` sle
			WHERE sle.is_cancelled = 0
			  AND sle.batch_no IS NOT NULL AND sle.batch_no != ''
			  AND (sle.serial_and_batch_bundle IS NULL OR sle.serial_and_batch_bundle = '')
			UNION ALL
			SELECT sle.item_code, sle.warehouse, sbe.batch_no,
			       sbe.qty,
			       (sbe.qty * COALESCE(sbe.incoming_rate, 0)) AS value_diff
			FROM `tabSerial and Batch Entry` sbe
			INNER JOIN `tabStock Ledger Entry` sle
			    ON sle.serial_and_batch_bundle = sbe.parent
			WHERE sle.is_cancelled = 0
			  AND sbe.batch_no IS NOT NULL AND sbe.batch_no != ''
		) x
		GROUP BY x.item_code, x.warehouse, x.batch_no
		HAVING SUM(x.qty) < -0.0001
		""",
		as_dict=True,
	)
	print(f"[find_donor_batches_for_negative] processing {len(negatives)} negative buckets")

	plan_inserted = 0
	plan_updated = 0
	repack_count = 0
	writeoff_count = 0

	for neg in negatives:
		item = neg["item_code"]
		wh = neg["warehouse"]
		neg_batch = neg["batch_no"]
		balance = float(neg["balance"])
		deficit = abs(balance)

		# Find donor — any batch on same (item, warehouse) with surplus >= deficit
		candidate_batches = frappe.db.sql_list(
			"""
			SELECT DISTINCT batch_no FROM (
				SELECT batch_no FROM `tabStock Ledger Entry`
				WHERE item_code=%s AND warehouse=%s
				  AND batch_no IS NOT NULL AND batch_no != ''
				  AND is_cancelled=0
				UNION
				SELECT sbe.batch_no FROM `tabSerial and Batch Entry` sbe
				INNER JOIN `tabStock Ledger Entry` sle ON sle.serial_and_batch_bundle = sbe.parent
				WHERE sle.item_code=%s AND sle.warehouse=%s
				  AND sbe.batch_no IS NOT NULL AND sbe.batch_no != ''
				  AND sle.is_cancelled=0
			) x
			""",
			(item, wh, item, wh),
		)
		donor = None
		donor_balance = 0.0
		for cand in candidate_batches:
			if cand == neg_batch:
				continue
			bal = _get_per_batch_balance(item, wh, cand)
			if bal >= deficit:
				donor = cand
				donor_balance = bal
				break  # first sufficient donor

		path = "REPACK" if donor else "WRITE_OFF"
		donor_val_rate = _get_donor_val_rate(item, wh, donor) if donor else 0.0
		est_value = abs(float(neg.get("value_diff") or 0))

		# Find existing plan row (don't duplicate; idempotent)
		existing_name = frappe.db.get_value(
			"Negative Batch Cleanup Plan",
			{"item_code": item, "warehouse": wh, "neg_batch_no": neg_batch},
			"name",
		)
		fields_dict = {
			"company": wh_to_co.get(wh, ""),
			"warehouse": wh,
			"item_code": item,
			"neg_batch_no": neg_batch,
			"deficit_qty": deficit,
			"neg_balance": balance,
			"snapshot_date": now,
			"path": path,
			"donor_batch_no": donor,
			"donor_surplus": donor_balance,
			"donor_val_rate": donor_val_rate,
			"estimated_value_company_currency": est_value,
		}

		if existing_name:
			doc = frappe.get_doc("Negative Batch Cleanup Plan", existing_name)
			# Don't touch rows already Done — those Repacks are committed
			if doc.status == "Done":
				continue
			# Refresh data on Pending / Ready / Failed rows
			for k, v in fields_dict.items():
				doc.set(k, v)
			doc.save(ignore_permissions=True)
			plan_updated += 1
		else:
			doc = frappe.new_doc("Negative Batch Cleanup Plan")
			for k, v in fields_dict.items():
				doc.set(k, v)
			doc.status = "Pending"
			doc.insert(ignore_permissions=True)
			plan_inserted += 1

		if path == "REPACK":
			repack_count += 1
		else:
			writeoff_count += 1

	frappe.db.commit()
	frappe.clear_cache(doctype="Negative Batch Cleanup Plan")
	print(
		f"[find_donor_batches_for_negative] inserted={plan_inserted} updated={plan_updated} "
		f"path_REPACK={repack_count} path_WRITE_OFF={writeoff_count}"
	)
