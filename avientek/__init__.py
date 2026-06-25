
__version__ = '0.0.11'


def _apply_patches():
	"""Apply monkey-patches at app load time."""
	try:
		from avientek.api.quotation_access import patch_shared_document_filter
		patch_shared_document_filter()
	except Exception:
		pass

	try:
		_patch_has_user_permission()
	except Exception:
		pass


def _patch_has_user_permission():
	"""Monkey-patch frappe.permissions.has_user_permission to skip child-row
	checks for our restricted doctypes.

	Frappe's has_user_permission iterates ALL child rows and checks each
	link field (Brand, Item Group) against User Permissions. This blocks
	documents with mixed brands/item groups even when our
	permission_query_conditions + has_permission hook already approved them.

	This patch: when the parent doctype is in our restricted set and has
	at least one matching child item (verified via SQL), skip the
	child-row User Permission check entirely.
	"""
	import frappe.permissions as perms

	_original_has_user_permission = perms.has_user_permission

	def patched_has_user_permission(doc, user=None, debug=False, ptype=None):
		import frappe
		from avientek.api.quotation_access import (
			BRAND_DOCTYPES, ITEM_GROUP_DOCTYPES,
			_get_user_brands, _get_user_item_groups,
		)

		if not user:
			user = frappe.session.user

		if user == "Administrator":
			return _original_has_user_permission(doc, user, debug=debug, ptype=ptype)

		doctype = doc.get("doctype") if hasattr(doc, "get") else getattr(doc, "doctype", None)
		docname = doc.get("name") if hasattr(doc, "get") else getattr(doc, "name", None)

		# Only patch for our restricted child-item doctypes
		child_dt = None
		if doctype:
			child_dt = BRAND_DOCTYPES.get(doctype) or ITEM_GROUP_DOCTYPES.get(doctype)

		if not child_dt or not docname:
			return _original_has_user_permission(doc, user, debug=debug, ptype=ptype)

		brand_perms = _get_user_brands(user)
		ig_perms = _get_user_item_groups(user)

		if not brand_perms and not ig_perms:
			return _original_has_user_permission(doc, user, debug=debug, ptype=ptype)

		# Check if document has at least one matching child item via SQL
		# (avoids loading child items which triggers the very check we're patching)
		has_match = False
		items = frappe.db.sql(
			"SELECT brand, item_group FROM `tab{dt}` WHERE parent = %s".format(dt=child_dt),
			docname, as_dict=True,
		)
		for item in items:
			ib = item.get("brand") or ""
			ig = item.get("item_group") or ""
			brand_ok = not brand_perms or not ib or ib in brand_perms
			ig_ok = not ig_perms or not ig or ig in ig_perms
			if brand_ok and ig_ok:
				has_match = True
				break

		if has_match:
			# Document has matching items — skip child-row User Permission
			# check but still check parent-level fields
			from frappe.core.doctype.user_permission.user_permission import get_user_permissions

			user_permissions = get_user_permissions(user)
			if not user_permissions:
				return True

			# Check parent-level link fields only (not children)
			meta = frappe.get_meta(doctype)
			for field in meta.get_link_fields():
				if field.ignore_user_permissions:
					continue
				if not doc.get(field.fieldname):
					continue
				if field.options not in user_permissions:
					continue
				allowed_docs = perms.get_allowed_docs_for_doctype(
					user_permissions.get(field.options, []), doctype
				)
				if allowed_docs and str(doc.get(field.fieldname)) not in allowed_docs:
					return False

			return True  # Parent checks passed, skip child checks

		return _original_has_user_permission(doc, user, debug=debug, ptype=ptype)

	perms.has_user_permission = patched_has_user_permission


def _patch_qb_get_query():
	"""Fix Frappe bug where frappe.qb.get_query() receives ignore_permissions
	kwarg which Engine.get_query() doesn't support. Strip it before passing.

	frappe.qb is a LocalProxy that's only available after frappe.init(),
	so we patch the underlying utility function instead.
	"""
	import frappe.query_builder.utils as qb_utils

	_original_get_query = qb_utils.get_query

	def _patched_get_query(*args, **kwargs):
		kwargs.pop("ignore_permissions", None)
		return _original_get_query(*args, **kwargs)

	qb_utils.get_query = _patched_get_query


def _patch_get_stock_ledgers_batches():
	"""Exclude SBB-linked SLEs from the legacy batch_no qty path.

	Sridhar 2026-05-25 (AETPL auto-FIFO failure on I030009 / BN14450):
	`get_auto_batch_nos` (the auto-FIFO entry point at DN submit) does:

	    available = get_available_batches(kwargs)        # SBB-aware (SBE.qty)
	    stock_ledgers = get_stock_ledgers_batches(kwargs)# legacy SLE.batch_no
	    update_available_batches(available, stock_ledgers, ...)
	    # for each batch already in available, batch.qty += stock_ledgers.qty
	    # — DOUBLE-COUNT when an SLE has BOTH batch_no AND a non-empty SBB.

	After the 2026-05-25 revert_multi_batch_sle_batch_no patch NULLed
	SLE.batch_no on every multi-batch SBB SLE, the legacy path under-
	counts outflows (it only sees the single-batch SLEs). The remaining
	single-batch SLE rows still have BOTH batch_no AND SBB set — so
	get_stock_ledgers_batches counts each of them once, and
	get_available_batches counts them AGAIN via SBE.qty. Result: every
	batch with single-batch SLEs that also has multi-batch outflows
	elsewhere shows phantom positive qty in the auto-picker. AETPL
	auto-FIFO on I030009 picked BN14450 (real qty 0) and submit failed.

	Fix: filter the legacy query to only consider SLEs WITHOUT an SBB
	link. Those are the pre-v15 / direct-batch-field rows that the SBB
	path cannot see. Modern v15 rows are exclusively in the SBB path.

	Idempotent — replaces the function once at app load.
	"""
	from erpnext.stock.doctype.serial_and_batch_bundle import serial_and_batch_bundle as sbb_mod

	_original = sbb_mod.get_stock_ledgers_batches

	def _patched_get_stock_ledgers_batches(kwargs):
		import frappe
		from frappe.utils import today, nowtime
		from erpnext.stock.utils import get_combine_datetime

		sle = frappe.qb.DocType("Stock Ledger Entry")
		batch = frappe.qb.DocType("Batch")
		from frappe.query_builder.functions import Sum

		query = (
			frappe.qb.from_(sle)
			.inner_join(batch)
			.on(sle.batch_no == batch.name)
			.select(
				sle.warehouse,
				sle.item_code,
				Sum(sle.actual_qty).as_("qty"),
				sle.batch_no,
				batch.expiry_date,
			)
			.where(
				(sle.is_cancelled == 0)
				& (sle.batch_no.isnotnull())
				& ((sle.serial_and_batch_bundle.isnull()) | (sle.serial_and_batch_bundle == ""))
			)
			.groupby(sle.batch_no, sle.warehouse)
		)

		for field in ["warehouse", "item_code", "batch_no"]:
			if not kwargs.get(field):
				continue
			if isinstance(kwargs.get(field), list):
				query = query.where(sle[field].isin(kwargs.get(field)))
			else:
				query = query.where(sle[field] == kwargs.get(field))

		if not kwargs.get("for_stock_levels"):
			query = query.where((batch.expiry_date >= today()) | (batch.expiry_date.isnull()))

		if kwargs.get("posting_date"):
			if kwargs.get("posting_time") is None:
				kwargs.posting_time = nowtime()

			ts_cond = sle.posting_datetime <= get_combine_datetime(
				kwargs.posting_date, kwargs.posting_time
			)
			if kwargs.get("creation"):
				ts_cond = sle.posting_datetime < get_combine_datetime(
					kwargs.posting_date, kwargs.posting_time
				)
				ts_cond |= (
					sle.posting_datetime == get_combine_datetime(
						kwargs.posting_date, kwargs.posting_time
					)
				) & (sle.creation < kwargs.creation)
			query = query.where(ts_cond)

		if kwargs.get("ignore_voucher_nos"):
			query = query.where(sle.voucher_no.notin(kwargs.get("ignore_voucher_nos")))

		if kwargs.get("based_on") == "LIFO":
			query = query.orderby(batch.creation, order=frappe.qb.desc)
		elif kwargs.get("based_on") == "Expiry":
			query = query.orderby(batch.expiry_date)
		else:
			query = query.orderby(batch.creation)

		data = query.run(as_dict=True)
		batches = {}
		for d in data:
			key = (d.batch_no, d.warehouse)
			if key not in batches:
				batches[key] = d
			else:
				batches[key].qty += d.qty
		return batches

	sbb_mod.get_stock_ledgers_batches = _patched_get_stock_ledgers_batches


def _patch_batch_wise_balance_history_legacy_query():
	"""Exclude SBB-linked SLEs from the Batch-Wise Balance History report's legacy query.

	Sridhar 2026-05-26 — the report at
	erpnext.stock.report.batch_wise_balance_history runs TWO queries and
	UNIONs the results:

	    1. get_stock_ledger_entries_for_batch_no — SUM(SLE.actual_qty)
	                                                WHERE batch_no != ""
	    2. get_stock_ledger_entries_for_batch_bundle — SUM(SBE.qty) via
	                                                   JOIN to SBB entries

	Pre-yesterday-morning, SBB-linked SLEs had batch_no = NULL (v15
	default), so the two paths were disjoint. After heal_sle_batch_no_from_sbb
	set batch_no on every SBB-linked SLE (single-batch ones got their
	correct batch; multi-batch ones got the first batch in idx order),
	the legacy query started matching single-batch SBB SLEs that are
	ALSO matched by the bundle query → every single-batch SBB
	transaction was counted TWICE in the report's running balance.

	After revert_multi_batch_sle_batch_no NULLed batch_no on multi-batch
	SBB SLEs, multi-batch lines dropped out of the legacy query but
	single-batch SBB SLEs (correctly kept by the heal) still have
	batch_no set. They remain double-counted by this report — surfaces
	as thousands of phantom negatives where the multi-batch inflow side
	can only show up via the bundle path but the single-batch outflow
	side shows up in both. BN09337 reported -89 at FZCO-7SEAS but
	Batch.batch_qty master = 0.

	Fix: legacy query additionally excludes SLEs that have a non-empty
	serial_and_batch_bundle. Modern v15 SBB-linked rows are exclusively
	in the bundle query. Pre-v15 orphan SLEs (no SBB) still flow through
	the legacy query.

	Idempotent — replaces the function once at app load.
	"""
	from erpnext.stock.report.batch_wise_balance_history import (
		batch_wise_balance_history as bwbh,
	)
	import frappe
	from frappe import _
	from frappe.utils import add_to_date, get_datetime
	from pypika import functions as fn

	def _patched_for_batch_no(filters):
		if not filters.get("from_date"):
			frappe.throw(_("'From Date' is required"))
		if not filters.get("to_date"):
			frappe.throw(_("'To Date' is required"))

		posting_datetime = get_datetime(add_to_date(filters["to_date"], days=1))
		sle = frappe.qb.DocType("Stock Ledger Entry")
		query = (
			frappe.qb.from_(sle)
			.select(
				sle.item_code,
				sle.warehouse,
				sle.batch_no,
				sle.posting_date,
				fn.Sum(sle.actual_qty).as_("actual_qty"),
				fn.Sum(sle.stock_value_difference).as_("stock_value_difference"),
			)
			.where(
				(sle.docstatus < 2)
				& (sle.is_cancelled == 0)
				& (sle.batch_no != "")
				& (sle.posting_datetime < posting_datetime)
				& ((sle.serial_and_batch_bundle.isnull()) | (sle.serial_and_batch_bundle == ""))
			)
			.groupby(sle.voucher_no, sle.batch_no, sle.item_code, sle.warehouse)
		)

		# replicate apply_warehouse_filter inline (avoids extra import cycles)
		from erpnext.stock.doctype.warehouse.warehouse import apply_warehouse_filter
		query = apply_warehouse_filter(query, sle, filters)

		if filters.get("warehouse_type") and not filters.get("warehouse"):
			warehouses = frappe.get_all(
				"Warehouse",
				filters={"warehouse_type": filters.warehouse_type, "is_group": 0},
				pluck="name",
			)
			if warehouses:
				query = query.where(sle.warehouse.isin(warehouses))

		for field in ["item_code", "batch_no", "company"]:
			if filters.get(field):
				query = query.where(sle[field] == filters.get(field))

		return query.run(as_dict=True) or []

	bwbh.get_stock_ledger_entries_for_batch_no = _patched_for_batch_no


def _patch_batch_valuation_get_sle_for_batches():
	"""Exclude SBB-linked SLEs from the legacy ledger-sum used by SBB
	submit-time validate_negative_batch.

	Sridhar 2026-06-03 (BN14571 / DN-AT-26-00332 still blocked despite
	prior patches):

	When a DN with batch-tracked items is submitted, ERPNext builds a
	Serial and Batch Bundle (SBB) and validates it via
	SerialAndBatchBundle.set_incoming_rate, which calls
	BatchNoValuation.calculate_avg_rate:

	    entries = self.get_batch_no_ledgers()         # SBB child rows only
	    for ledger in entries:
	        self.available_qty[batch] += qty
	    self.calculate_avg_rate_from_deprecarated_ledgers()
	        # ↑ adds SLE.actual_qty WHERE batch_no IS NOT NULL — does NOT
	        #   exclude SBB-linked SLEs, so single-batch SBB rows are
	        #   counted TWICE (once via SBE.qty, once via SLE.batch_no).
	    # Then validate_negative_batch throws if self.available_qty[batch] < 0

	Result: validate_negative_batch reads an INFLATED outflow total, sees
	the batch as more negative than it really is, throws
	"Batch No X of an Item Y has negative stock of quantity -1.0".

	Concrete proof on local: BN14571 (I028753 / Stores-KSA) shows
	  Old buggy query: -2.0
	  TRUE SBB-aware:  +3.0
	Yet DN-AT-26-00332 still throws -1.0 because this third validation
	path uses the SAME upstream bug. The picker patch and the report
	patch were not enough — submit validation also needs the SBB
	exclusion.

	Fix: monkey-patch DeprecatedBatchNoValuation.get_sle_for_batches to
	add the same `serial_and_batch_bundle IS NULL` filter as the other
	two patches. Modern v15 SBB-linked rows flow exclusively through
	get_batch_no_ledgers (the SBB path). Only true pre-v15 / direct-
	batch-field SLEs go through this legacy path.

	Idempotent — replaces the bound method once at app load.
	"""
	import datetime
	import frappe
	from frappe.utils import nowtime
	from frappe.query_builder.functions import Sum
	from erpnext.stock import deprecated_serial_batch as dsb

	def _patched_get_sle_for_batches(self):
		from erpnext.stock.utils import get_combine_datetime

		if not self.batchwise_valuation_batches:
			return []

		sle = frappe.qb.DocType("Stock Ledger Entry")

		timestamp_condition = None
		if self.sle.posting_date:
			if self.sle.posting_time is None:
				self.sle.posting_time = nowtime()

			posting_datetime = get_combine_datetime(self.sle.posting_date, self.sle.posting_time)
			if not self.sle.creation:
				posting_datetime = posting_datetime + datetime.timedelta(milliseconds=1)

			timestamp_condition = sle.posting_datetime < posting_datetime

			if self.sle.creation:
				timestamp_condition |= (sle.posting_datetime == posting_datetime) & (
					sle.creation < self.sle.creation
				)

		query = (
			frappe.qb.from_(sle)
			.select(
				sle.batch_no,
				Sum(sle.stock_value_difference).as_("batch_value"),
				Sum(sle.actual_qty).as_("batch_qty"),
			)
			.where(
				(sle.item_code == self.sle.item_code)
				& (sle.warehouse == self.sle.warehouse)
				& (sle.batch_no.isin(self.batchwise_valuation_batches))
				& (sle.batch_no.isnotnull())
				& (sle.is_cancelled == 0)
				# Avientek fix — exclude SBB-linked SLEs to stop the
				# double-count with get_batch_no_ledgers (SBE.qty path).
				& ((sle.serial_and_batch_bundle.isnull()) | (sle.serial_and_batch_bundle == ""))
			)
			.for_update()
			.groupby(sle.batch_no)
		)

		if timestamp_condition:
			query = query.where(timestamp_condition)

		if self.sle.name:
			query = query.where(sle.name != self.sle.name)

		return query.run(as_dict=True)

	dsb.DeprecatedBatchNoValuation.get_sle_for_batches = _patched_get_sle_for_batches


def _patch_validate_negative_batch_respect_setting():
	"""Sammish 2026-06-18 (DN-LLC-26-00687) — fourth patch in the
	negative-batch family.

	Background: ERPNext's SerialAndBatchBundle has TWO places that throw
	BatchNegativeStockError when computed batch availability < 0:
	  1. validate_batch_inventory (line 1474) — calls validate_negative_batch
	     INSIDE a block that already short-circuits when
	     Stock Settings.allow_negative_stock_for_batch is enabled. Path
	     respects the setting.
	  2. set_incoming_rate_for_outward_transaction (line 633) — calls
	     validate_negative_batch DIRECTLY, gated only by the doc-level
	     `allow_negative_stock` flag (not the batch-level setting).

	Path 2 is the one that fires today on DN-LLC-26-00687 with the
	phantom error "negative stock of quantity -2.0 in Stores - AETL"
	even though Bin shows +5 and SBE ledger sums to +5. The
	available_qty computed by BatchNoValuation +
	DeprecatedBatchNoValuation legacy walker disagrees with the SQL
	ground truth — same class of double-count we patched in three other
	functions above, but in a NEW code path that the prior patches
	don't reach. Could not reproduce on local v15.109.1 (same code
	exists, but the data shape on prod triggers the bug uniquely).

	Fix: make validate_negative_batch ALSO honor
	`Stock Settings.allow_negative_stock_for_batch=1` (which Avientek's
	`enable_allow_negative_stock_for_batch` patch already ensures). When
	the setting is enabled, this method short-circuits — leaving
	Avientek's `batch_negative_guard` (before_submit hook on DN/SI/SE/PR)
	as the SOLE per-batch validator. The guard uses correct SBE-aware
	SQL and won't false-positive.

	Same idempotent pattern as the other 3 patches in this file.
	"""
	from erpnext.stock.doctype.serial_and_batch_bundle import serial_and_batch_bundle as sbb_mod

	import frappe

	_original_validate_negative_batch = sbb_mod.SerialandBatchBundle.validate_negative_batch

	def _patched_validate_negative_batch(self, batch_no, available_qty):
		# Honor Stock Settings.allow_negative_stock_for_batch at THIS
		# call site too (the other call site in validate_batch_inventory
		# already does so). Avientek's batch_negative_guard remains the
		# sole per-batch validator when this is enabled.
		if frappe.db.get_single_value(
			"Stock Settings", "allow_negative_stock_for_batch"
		):
			return
		return _original_validate_negative_batch(self, batch_no, available_qty)

	sbb_mod.SerialandBatchBundle.validate_negative_batch = _patched_validate_negative_batch


_apply_patches()
_patch_qb_get_query()
try:
	_patch_get_stock_ledgers_batches()
except Exception:
	pass
try:
	_patch_batch_wise_balance_history_legacy_query()
except Exception:
	pass
try:
	_patch_batch_valuation_get_sle_for_batches()
except Exception:
	pass
try:
	_patch_validate_negative_batch_respect_setting()
except Exception:
	pass


def _patch_safer_get_meta_v15_111():
	"""Sridhar/Venkatesh 2026-06-11: Frappe v15.111.0 added
	`safer_get_meta` in frappe/utils/safe_exec.py and registered it as
	the `frappe.get_meta` shadow inside the sandboxed Jinja env used by
	Print Format rendering. Unfortunately the wrapper returns
	`doc.as_dict()` (a `frappe._dict`) instead of the Meta object:

	    def safer_get_meta(doctype, cached=True):
	        assert isinstance(doctype, str)
	        assert isinstance(cached, bool)
	        doc = frappe.get_meta(doctype, cached=cached)
	        return doc.as_dict() if doc else None

	But ERPNext's standard print template `standard_macros.html` does:

	    {%- set table_meta = frappe.get_meta(df.options) -%}
	    ...
	    docfield = table_meta.get_field(col_df.get("fieldname"))

	With `table_meta` now a `_dict`, `table_meta.get_field` is
	`_dict.get('get_field')` which is None. Calling None(...) raises
	`'NoneType' object is not callable`, and EVERY Print Format with
	a visible_columns child-table block (e.g. Avientek's "Quote print
	2026") errors at line 19 of `print_formats/standard.html`.

	This was reported on prod within hours of the Bench Update bumping
	Frappe 15.109 → 15.111 (commit hash on prod showed 15.111.0).

	Fix: monkey-patch `safer_get_meta` to keep the assertions (input-
	type safety) but return the actual Meta object — the same object
	the unwrapped `frappe.get_meta` returns, which has the `get_field`
	method consumers rely on.

	Idempotent. Safe on older Frappe (the module attribute won't exist
	pre-15.111.0 and we skip silently).
	"""
	try:
		import frappe
		from frappe.utils import safe_exec
	except Exception:
		return

	if not hasattr(safe_exec, "safer_get_meta"):
		return  # pre-15.111.0 Frappe — no patch needed

	def _patched_safer_get_meta(doctype, cached=True):
		assert isinstance(doctype, str)
		assert isinstance(cached, bool)
		return frappe.get_meta(doctype, cached=cached)

	safe_exec.safer_get_meta = _patched_safer_get_meta


try:
	_patch_safer_get_meta_v15_111()
except Exception:
	pass


def _patch_pr_dashboard_lcv_count():
	"""Show submitted Landed Cost Voucher names + count in the Purchase
	Receipt 'Connections' panel.

	Sridhar 2026-06-13 via WhatsApp on GRN-FZCO-26-00448 — the form's
	Connections section listed the label "Landed Cost Voucher" but with
	no badge / count, leaving the user with no clickable path to the
	LCV that posted the freight & documentation GL lines (the very lines
	Sridhar flagged as "not showing on PR").

	Root cause in ERPNext's standard PR dashboard config
	(erpnext/stock/doctype/purchase_receipt/purchase_receipt_dashboard.get_data):

	    non_standard_fieldnames["Landed Cost Voucher"] = "receipt_document"
	    transactions += [{"label": "Related",
	                      "items": [..., "Landed Cost Voucher", ...]}]

	The mapping is wrong — `receipt_document` is a field on the CHILD
	doctype `Landed Cost Purchase Receipt`, not on the LCV parent. So
	Frappe's get_external_links runs

	    frappe.db.count("Landed Cost Voucher",
	                    {"receipt_document": pr_name})

	→ SQL: "Unknown column 'receipt_document' in 'WHERE'". The error is
	swallowed inside get_doc_count → count = 0 → badge is empty.

	Meanwhile Frappe's `internal_links` mechanism only walks fields on
	the CURRENT doc (a parent field or [child_table, link_field] within
	the current doc) — it cannot reverse-resolve through a foreign
	child table.

	Fix: monkey-patch `frappe.desk.notifications._get_linked_document_counts`
	to detect PR doctype and append a properly-formed `internal_links_found`
	entry for Landed Cost Voucher with both `count` AND clickable `names`.

	Idempotent. Hasattr-guarded — silently skips on Frappe versions
	that don't have the function under this name (forward-compat). On
	any per-call error inside the patch body the original result is
	returned unmodified — never regresses other Connections badges.
	"""
	try:
		from frappe.desk import notifications
	except Exception:
		return

	if not hasattr(notifications, "_get_linked_document_counts"):
		return

	_original = notifications._get_linked_document_counts

	def _patched(doctype, name, items=None):
		import frappe

		out = _original(doctype, name, items=items)

		if doctype != "Purchase Receipt":
			return out

		try:
			inner = out.get("count") or {}
			external = inner.get("external_links_found") or []
			internal = inner.get("internal_links_found") or []

			external = [
				e for e in external if e.get("doctype") != "Landed Cost Voucher"
			]
			already = any(
				e.get("doctype") == "Landed Cost Voucher" for e in internal
			)

			if not already:
				rows = frappe.db.sql(
					"""
					SELECT DISTINCT lcv.name
					FROM `tabLanded Cost Voucher` lcv
					INNER JOIN `tabLanded Cost Purchase Receipt` lpr
					    ON lpr.parent = lcv.name
					WHERE lpr.receipt_document = %s
					  AND lcv.docstatus < 2
					ORDER BY lcv.name
					""",
					(name,),
				)
				names = [r[0] for r in rows]
				if names:
					internal.append(
						{
							"doctype": "Landed Cost Voucher",
							"count": len(names),
							"open_count": 0,
							"names": names,
						}
					)

			inner["external_links_found"] = external
			inner["internal_links_found"] = internal
			out["count"] = inner
		except Exception:
			pass

		return out

	notifications._get_linked_document_counts = _patched


try:
	_patch_pr_dashboard_lcv_count()
except Exception:
	pass


def _patch_query_report_export_keeps_date_typed():
	"""Sammish 2026-06-20 (Jithin Batch-Wise Ageing Report Excel): Date
	columns in the downloaded xlsx were landing as TEXT cells instead
	of typed Excel dates, so Excel couldn't sort / filter by date and
	the autofilter dropdown listed each formatted string separately.

	Root cause in Frappe core
	-------------------------
	`frappe.desk.query_report._export_query` calls
	`frappe.desk.query_report.format_fields` BEFORE handing the data to
	`make_xlsx`. format_fields walks every Date / Datetime column and
	does:

	    row[index] = formatdate(val)         # for Date
	    row[index] = format_datetime(val)    # for Datetime

	→ The cell value reaches make_xlsx as a *string* (e.g. "11-10-2024")
	instead of a `datetime.date`. make_xlsx's typed-cell branch checks
	`isinstance(value, datetime.date | datetime.datetime)` (xlsxutils.py
	line 63) → fails → falls through to plain text cell.

	Fix
	---
	Monkey-patch format_fields to skip the Date / Datetime branches.
	make_xlsx then sees the raw datetime.date object, takes the typed-
	cell path, and emits an Excel cell with `number_format` from
	System Settings.date_format — so dates remain visually formatted
	the way the user expects, AND Excel treats them as real dates for
	sort / filter / formula purposes.

	Other branches (Duration, Currency-with-precision) preserved
	unchanged — they format to strings/floats that make_xlsx already
	handles correctly.

	Scope: GLOBAL across every Frappe Query Report on this site
	(Batch-Wise Ageing, Stock Ageing, Sales Register, Purchase
	Register, all custom reports, etc.). Doesn't affect Frappe's
	Report Builder export (different code path that already gives
	typed cells).

	Idempotent — replaces the function once at app load. Forward-
	compatible — if Frappe ever fixes this in core, our patch
	produces the same result (typed dates).
	"""
	try:
		import frappe.desk.query_report as qr_mod
	except Exception:
		return

	from frappe.utils import format_duration
	import datetime as _dt

	def _patched_format_fields(data):
		for i, col in enumerate(data.columns):
			if col.get("fieldtype") == "Duration":
				for row in data.result:
					index = col.get("fieldname") if isinstance(row, dict) else i
					val = row.get(index) if isinstance(row, dict) else row[index]
					if val:
						row[index] = format_duration(val)
			elif col.get("fieldtype") == "Currency" and col.get("precision"):
				for row in data.result:
					index = col.get("fieldname") if isinstance(row, dict) else i
					val = row.get(index) if isinstance(row, dict) else row[index]
					if val:
						row[index] = round(val, col.get("precision"))
			elif col.get("fieldtype") in ("Date", "Datetime"):
				# Sammish 2026-06-25 (Sridhar TSK-2026-00383 TC3/TC4/TC7
				# failures on qcs-avntk-test): skip formatdate() to keep
				# date objects typed — AND coerce stray empty-string /
				# non-date values in this column to None so Excel's
				# column-type inference still classifies the column as
				# Date.
				#
				# Background: reports like General Ledger and Sales
				# Register insert SUMMARY rows (Opening / Total /
				# Closing / opening_row) as dicts that lack the
				# posting_date key entirely. xlsxutils.build_xlsx_data
				# falls back to `row.get(fieldname, row.get(label, ""))`
				# → "" (empty string) → Excel writes that as a TEXT
				# cell. Even ONE text cell in the column makes Excel's
				# AutoFilter classify the whole column as text →
				# Text Filters dropdown + flat string list instead of
				# the Date Filters tree (year → month → day).
				#
				# Coercing "" / non-date strings to None makes openpyxl
				# emit an empty cell (not a text cell with empty
				# content), so the column stays cleanly typed as Date.
				# Genuine date-strings (rare but possible from raw SQL)
				# are left untouched so make_xlsx's coercion path can
				# still try to parse them.
				for row in data.result:
					index = col.get("fieldname") if isinstance(row, dict) else i
					if isinstance(row, dict):
						val = row.get(index)
					else:
						try:
							val = row[index]
						except (IndexError, TypeError):
							continue
					# Leave real date/datetime objects alone (they're
					# what we WANT make_xlsx to receive raw).
					if isinstance(val, (_dt.date, _dt.datetime)):
						continue
					# Coerce empty/whitespace strings + None to None so
					# the summary-row cells become empty Excel cells
					# instead of text cells.
					if val is None or (isinstance(val, str) and not val.strip()):
						if isinstance(row, dict):
							row[index] = None
						else:
							row[index] = None

	qr_mod.format_fields = _patched_format_fields


try:
	_patch_query_report_export_keeps_date_typed()
except Exception:
	pass


def _patch_india_compliance_round_off_accounts_signature():
	"""Sammish 2026-06-24 (PROD URGENT, avientekv21.frappe.cloud, Sales Order
	create broken with HTTP 500): ERPNext core's `get_round_off_applicable_accounts`
	was updated to pass THREE positional args to the regional override:

	    return get_regional_round_off_accounts(company, account_list, doc)

	The india_compliance override (gst_india.overrides.transaction.
	get_regional_round_off_accounts) on this bench still has the OLDER
	2-arg signature:

	    def get_regional_round_off_accounts(company, account_list):

	Result: every Sales Order / Sales Invoice form load on an India
	company hits a 500 with
	    TypeError: get_regional_round_off_accounts() takes 2 positional
	    arguments but 3 were given.

	Triggered by today's Frappe Cloud deploy (ksa_compliance install also
	bumped ERPNext to a version that uses the new 3-arg call site, but
	india_compliance wasn't bumped in lockstep).

	FIX: wrap the override to accept and discard the extra `doc` arg.
	The 3rd arg in ERPNext's call is passed for future use (regional code
	may need to introspect doc context); india_compliance's current
	implementation does not need it — its 2-arg behavior remains
	semantically correct.

	Self-deactivating: introspects the current signature first. If
	india_compliance gets bumped to a 3-arg version upstream, the patch
	becomes a no-op (skips wrapping).
	"""
	try:
		from india_compliance.gst_india.overrides import transaction as tx_mod
	except Exception:
		return  # india_compliance not installed — nothing to patch

	import inspect
	current = getattr(tx_mod, "get_regional_round_off_accounts", None)
	if current is None:
		return

	try:
		params = inspect.signature(current).parameters
	except (TypeError, ValueError):
		return  # builtins / C-extensions — leave alone

	# Count positional-or-keyword params (not *args/**kwargs catch-alls)
	concrete = [p for p in params.values()
	            if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
	                          inspect.Parameter.POSITIONAL_OR_KEYWORD)]
	if len(concrete) >= 3:
		return  # already 3-arg compatible — no patch needed

	# Has *args catch-all? Also fine — caller's extra positional flows in.
	if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params.values()):
		return

	_orig = current

	def _wrapped(company, account_list, *args, **kwargs):
		# Discard the extra `doc` arg (and any future additions)
		return _orig(company, account_list)

	tx_mod.get_regional_round_off_accounts = _wrapped


try:
	_patch_india_compliance_round_off_accounts_signature()
except Exception:
	pass

