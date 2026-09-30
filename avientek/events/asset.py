import frappe


def default_asset_owner_company(doc, method=None):
	"""#0544 follow-up (accounts.ksa, AS-0926-00001 from GRN-KSA-26-00183):
	assets auto-created from a Purchase Receipt leave Asset Owner and Asset
	Owner Company blank. With "Apply Strict User Permissions" ON, a user
	restricted by Company is refused any document whose Company-link field is
	EMPTY ("linked to Company 'empty' in field Asset Owner Company"), so the
	user who just received the item cannot open the asset.

	An Avientek asset is owned by the company that bought it: when blank,
	default Asset Owner to "Company" and Asset Owner Company to doc.company.
	Never overrides a value the user chose (Supplier / Customer owner, or a
	different owner company)."""
	if not doc.get("asset_owner"):
		doc.asset_owner = "Company"
	if doc.asset_owner == "Company" and not doc.get("asset_owner_company") and doc.get("company"):
		doc.asset_owner_company = doc.company
