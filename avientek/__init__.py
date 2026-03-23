
__version__ = '0.0.11'


def _apply_shared_doc_patch():
	"""Apply monkey-patch to enforce permission_query_conditions on shared documents.
	Without this, documents shared with a user bypass all custom permission filters.
	"""
	try:
		from avientek.api.quotation_access import patch_shared_document_filter
		patch_shared_document_filter()
	except Exception:
		pass  # Fail silently during install/setup


_apply_shared_doc_patch()

