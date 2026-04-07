
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


_apply_patches()
_patch_qb_get_query()

